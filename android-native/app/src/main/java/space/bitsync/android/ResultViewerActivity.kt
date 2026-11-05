package space.bitsync.android

import android.content.*
import android.graphics.Bitmap
import android.net.Uri
import android.os.*
import android.view.*
import android.webkit.*
import android.widget.*
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.snackbar.Snackbar
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.util.concurrent.Executors

/** Native result chrome, native image/PDF viewer, isolated HTML document surface. */
class ResultViewerActivity:AppCompatActivity() {
    private val worker=Executors.newSingleThreadExecutor()
    private lateinit var api:ApiSession
    private lateinit var result:NativeResult
    private lateinit var root:LinearLayout
    private lateinit var stage:FrameLayout
    private lateinit var progress:LinearProgressIndicator
    private lateinit var image:ZoomImageView
    private lateinit var pageLabel:TextView
    private lateinit var navigation:LinearLayout
    private lateinit var previous:MaterialButton
    private lateinit var next:MaterialButton
    private var original:File?=null
    private var pdf:Messenger?=null
    private var pdfBound=false
    private var web:WebView?=null
    private var htmlSource=""
    private var wide=false
    private var page=0
    private var pages=1
    private var renderVersion=0
    private var officePath:String?=null
    private val save=registerForActivityResult(ActivityResultContracts.CreateDocument("*/*")){uri->
        val source=original
        if(uri!=null&&source!=null)work {contentResolver.openOutputStream(uri)?.use{out->source.inputStream().use{it.copyTo(out)}}?:error("Не удалось сохранить файл");ui{notice("Файл сохранён")}}
    }
    private val reply=Messenger(object:Handler(Looper.getMainLooper()){
        override fun handleMessage(message:Message){
            if(isDestroyed)return
            when(message.what){
                1->{pages=message.arg1;page=page.coerceIn(0,pages-1);renderPage()}
                2->{
                    @Suppress("DEPRECATION") val bitmap=message.data.getParcelable<Bitmap>("bitmap")
                    if(message.arg2==renderVersion&&bitmap!=null){image.show(bitmap);progress.visibility=View.INVISIBLE;updateNavigation()}
                }
                3->showError(message.data.getString("error")?:"Не удалось открыть PDF")
            }
        }
    })
    private val connection=object:ServiceConnection {
        override fun onServiceConnected(name:ComponentName,binder:IBinder){
            pdf=Messenger(binder)
            work {
                val descriptor=ParcelFileDescriptor.open(requireNotNull(original),ParcelFileDescriptor.MODE_READ_ONLY)
                try{pdf?.send(Message.obtain(null,1).apply{replyTo=reply;data=Bundle().apply{putParcelable("file",descriptor)}})}finally{descriptor.close()}
            }
        }
        override fun onServiceDisconnected(name:ComponentName){pdf=null;showError("Просмотр PDF прервался. Закройте документ и откройте снова.")}
    }
    override fun onCreate(state:Bundle?){
        super.onCreate(state);enableEdgeToEdge();api=ApiSession(applicationContext)
        result=NativeResult(intent.getStringExtra("source").orEmpty(),intent.getStringExtra("name")?.take(180)?:"Результат",intent.getStringExtra("conversation").orEmpty())
        page=state?.getInt("page",0)?:0;wide=state?.getBoolean("wide",false)?:false
        root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setBackgroundColor(color(R.color.surface))};setContentView(root)
        ViewCompat.setOnApplyWindowInsetsListener(root){v,insets->val bars=insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout());val ime=insets.getInsets(WindowInsetsCompat.Type.ime());v.setPadding(bars.left,bars.top,bars.right,maxOf(bars.bottom,ime.bottom));insets}
        val toolbar=MaterialToolbar(this).apply{
            title=result.name;setTitleTextColor(color(R.color.on_surface));setNavigationIcon(R.drawable.ic_mode_close);setNavigationIconTint(color(R.color.on_surface_variant));navigationContentDescription="Закрыть результат";setNavigationOnClickListener{finish()}
            menu.add("Сохранить").setIcon(R.drawable.ic_result_save).setShowAsAction(MenuItem.SHOW_AS_ACTION_IF_ROOM)
            menu.add("Поделиться")
            if(result.kind==ResultKind.HTML)menu.add("Телефон / широкий вид")
            setOnMenuItemClickListener{item->when(item.title.toString()){
                "Сохранить"->withOriginal{save.launch(result.name)}
                "Поделиться"->withOriginal{share()}
                "Телефон / широкий вид"->{wide=!wide;loadCanvas()}
            };true}
        }
        root.addView(toolbar,LinearLayout.LayoutParams(-1,-2))
        progress=LinearProgressIndicator(this).apply{isIndeterminate=true};root.addView(progress,LinearLayout.LayoutParams(-1,dp(2)))
        stage=FrameLayout(this);root.addView(stage,LinearLayout.LayoutParams(-1,0,1f))
        image=ZoomImageView(this).apply{id=R.id.result_image};stage.addView(image,FrameLayout.LayoutParams(-1,-1))
        navigation=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL;setPadding(dp(16),dp(4),dp(16),dp(8));visibility=View.GONE}
        previous=button("Предыдущая"){if(page>0){page--;renderPage()}}
        next=button("Следующая"){if(page<pages-1){page++;renderPage()}}.apply{id=R.id.result_next}
        pageLabel=TextView(this).apply{id=R.id.result_page_label;gravity=Gravity.CENTER;textSize=13f;setTextColor(color(R.color.on_surface_variant))}
        navigation.addView(previous,LinearLayout.LayoutParams(-2,dp(48)));navigation.addView(pageLabel,LinearLayout.LayoutParams(0,-2,1f));navigation.addView(next,LinearLayout.LayoutParams(-2,dp(48)));root.addView(navigation)
        if(result.kind==ResultKind.HTML&&result.conversation.isNotBlank()) {
            val editRow=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL;setPadding(dp(16),dp(4),dp(16),dp(12))}
            val edit=EditText(this).apply{hint="Что изменить в результате?";textSize=15f;maxLines=3;minHeight=dp(48);setTextColor(color(R.color.on_surface));setHintTextColor(color(R.color.on_surface_variant))}
            editRow.addView(edit,LinearLayout.LayoutParams(0,-2,1f))
            editRow.addView(button("В чат"){
                val prompt=edit.text.toString().trim()
                if(prompt.isNotBlank()) {setResult(RESULT_OK,Intent().putExtra("edit",prompt.take(4000)).putExtra("source",result.source).putExtra("name",result.name).putExtra("conversation",result.conversation));finish()}
            },LinearLayout.LayoutParams(-2,dp(48)))
            root.addView(editRow)
        }
        work{
            api.restore()
            when(result.kind){
                ResultKind.OFFICE->{
                    require(result.conversation.matches(Regex("[A-Za-z0-9_-]{1,64}"))){"Для предпросмотра нужен файл беседы"}
                    val path="/conversations/${result.conversation}/files/preview?filename=${Uri.encode(result.name)}&mobile=true"
                    val info=JSONObject(api.api(path));officePath=path
                    ui{pages=info.getInt("pages");page=page.coerceIn(0,pages-1);renderPage()}
                }
                else->{original=ResultStore.load(applicationContext,api,result);ui{openOriginal()}}
            }
        }
    }
    private fun color(id:Int)=ContextCompat.getColor(this,id)
    private fun dp(n:Int)=(n*resources.displayMetrics.density).toInt()
    private fun button(text:String,action:()->Unit)=MaterialButton(this,null,com.google.android.material.R.attr.borderlessButtonStyle).apply{this.text=text;minHeight=dp(48);setOnClickListener{action()}}
    private fun ui(action:()->Unit){runOnUiThread{if(!isFinishing&&!isDestroyed)action()}}
    private fun work(action:()->Unit){if(worker.isShutdown)return;worker.execute{try{action()}catch(e:Exception){ui{showError(e.message?:"Не удалось открыть результат")}}}}
    private fun notice(text:String){Snackbar.make(root,text,Snackbar.LENGTH_LONG).setTextMaxLines(3).show()}
    private fun showError(text:String){progress.visibility=View.INVISIBLE;notice(text);val error=TextView(this).apply{this.text=text;gravity=Gravity.CENTER;setPadding(dp(24),dp(24),dp(24),dp(24));setTextColor(color(R.color.on_surface_variant))};stage.addView(error,FrameLayout.LayoutParams(-1,-1))}
    private fun openOriginal(){
        when(result.kind){
            ResultKind.IMAGE->work{val bitmap=ResultStore.bitmap(requireNotNull(original));ui{image.show(bitmap);progress.visibility=View.INVISIBLE}}
            ResultKind.PDF->{pdfBound=bindService(Intent(this,PdfRenderService::class.java),connection,Context.BIND_AUTO_CREATE);if(!pdfBound)showError("Не удалось открыть просмотр PDF")}
            ResultKind.HTML->{work{val file=requireNotNull(original);require(file.length()<=16*1024*1024){"Холст слишком большой"};htmlSource=file.readText(Charsets.UTF_8);ui{loadCanvas()}}}
            else->showError("Для этого формата доступны сохранение и отправка в другое приложение.")
        }
    }
    private fun renderPage(){
        updateNavigation();progress.visibility=View.VISIBLE;val token=++renderVersion
        if(result.kind==ResultKind.HTML){web?.evaluateJavascript("window.__btNativeShow&&window.__btNativeShow($page)",null);progress.visibility=View.INVISIBLE;return}
        val office=officePath
        if(office!=null)work {
            val file=ResultStore.load(applicationContext,api,NativeResult("$office&page=${page+1}","page-${page+1}.png",result.conversation))
            val bitmap=ResultStore.bitmap(file)
            ui{if(token==renderVersion){image.show(bitmap);progress.visibility=View.INVISIBLE}}
        }else runCatching{pdf?.send(Message.obtain(null,2,page,token).apply{replyTo=reply})}.onFailure{showError("Не удалось прочитать страницу")}
    }
    private fun updateNavigation(){navigation.visibility=if(pages>1)View.VISIBLE else View.GONE;pageLabel.text="${page+1} / $pages";previous.isEnabled=page>0;next.isEnabled=page<pages-1}
    @Suppress("SetJavaScriptEnabled") private fun loadCanvas(){
        web?.let{stage.removeView(it);it.destroy()};image.visibility=View.GONE;progress.visibility=View.VISIBLE
        val document=runCatching{CanvasDocument.prepare(htmlSource,wide)}.getOrElse{showError(it.message?:"Не удалось открыть холст");return}
        val viewer=WebView(this).apply{id=R.id.result_web}
        viewer.settings.apply{
            javaScriptEnabled=true;allowFileAccess=false;allowContentAccess=false;domStorageEnabled=false;databaseEnabled=false
            mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW;javaScriptCanOpenWindowsAutomatically=false
            setSupportMultipleWindows(false);setGeolocationEnabled(false);useWideViewPort=true;loadWithOverviewMode=true;builtInZoomControls=true;displayZoomControls=false
        }
        CookieManager.getInstance().setAcceptCookie(false)
        CookieManager.getInstance().setAcceptThirdPartyCookies(viewer,false)
        viewer.webChromeClient=object:WebChromeClient(){override fun onPermissionRequest(request:PermissionRequest){request.deny()}}
        viewer.webViewClient=object:WebViewClient(){
            override fun shouldInterceptRequest(view:WebView,request:WebResourceRequest):WebResourceResponse? {
                if(request.url.toString().substringBefore('#')==CanvasDocument.URL)return WebResourceResponse("text/html","utf-8",ByteArrayInputStream(document.toByteArray(Charsets.UTF_8)))
                if(request.url.scheme!="https"||request.isForMainFrame)return WebResourceResponse("text/plain","utf-8",403,"Blocked",emptyMap(),ByteArrayInputStream(ByteArray(0)))
                return null
            }
            override fun shouldOverrideUrlLoading(view:WebView,request:WebResourceRequest):Boolean {
                if(!request.isForMainFrame)return false
                if(request.url.toString().startsWith(CanvasDocument.URL+"#"))return false
                if(CanvasDocument.allowedNavigation(request.url.toString(),request.hasGesture()))runCatching{startActivity(Intent(Intent.ACTION_VIEW,request.url))}
                return true
            }
            override fun onPageFinished(view:WebView,url:String){
                progress.visibility=View.INVISIBLE
                view.evaluateJavascript("document.querySelectorAll('.slide').length"){count->pages=count.toIntOrNull()?.takeIf{it>0}?:1;page=page.coerceIn(0,pages-1);updateNavigation();if(pages>1)view.evaluateJavascript("window.__btNativeShow&&window.__btNativeShow($page)",null)}
            }
            override fun onRenderProcessGone(view:WebView,detail:RenderProcessGoneDetail):Boolean{stage.removeView(view);view.destroy();web=null;showError("Предпросмотр закрылся. Откройте результат снова.");return true}
        }
        web=viewer;stage.addView(viewer,FrameLayout.LayoutParams(-1,-1));viewer.loadUrl(CanvasDocument.URL)
    }
    private fun withOriginal(action:()->Unit){if(original!=null)action()else work{original=ResultStore.load(applicationContext,api,result);ui(action)}}
    private fun share(){val file=original?:return;val uri=FileProvider.getUriForFile(this,"$packageName.files",file);val mime=MimeTypeMap.getSingleton().getMimeTypeFromExtension(result.name.substringAfterLast('.',"").lowercase())?:"application/octet-stream";startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION),result.name))}
    override fun onSaveInstanceState(state:Bundle){state.putInt("page",page);state.putBoolean("wide",wide);super.onSaveInstanceState(state)}
    override fun onPause(){web?.onPause();super.onPause()}
    override fun onResume(){super.onResume();web?.onResume()}
    override fun onDestroy(){if(pdfBound)unbindService(connection);web?.let{stage.removeView(it);it.destroy()};worker.shutdownNow();super.onDestroy()}
    companion object {
        internal fun intent(context:Context,result:NativeResult)=Intent(context,ResultViewerActivity::class.java).putExtra("source",result.source).putExtra("name",result.name).putExtra("conversation",result.conversation)
    }
}
