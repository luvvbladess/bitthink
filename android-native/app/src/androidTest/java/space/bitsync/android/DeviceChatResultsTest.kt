package space.bitsync.android

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.BitmapDrawable
import android.graphics.pdf.PdfDocument
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.recyclerview.widget.RecyclerView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class DeviceChatResultsTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun waitFor(ms:Long=30000,condition:()->Boolean){val end=System.currentTimeMillis()+ms;while(System.currentTimeMillis()<end){instrumentation.waitForIdleSync();if(condition())return;Thread.sleep(100)};fail("Chat result did not become available")}
    private fun views(view:View):List<View> = listOf(view)+if(view is ViewGroup)(0 until view.childCount).flatMap{views(view.getChildAt(it))}else emptyList()
    private fun foregroundViewer():ResultViewerActivity? {
        fun current()=ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED).filterIsInstance<ResultViewerActivity>().firstOrNull()
        if(android.os.Looper.myLooper()==android.os.Looper.getMainLooper())return current()
        val ref=AtomicReference<ResultViewerActivity>();instrumentation.runOnMainSync{current()?.let{ref.set(it)}};return ref.get()
    }
    private fun viewerBitmap():Bitmap? {val ref=AtomicReference<Bitmap>();instrumentation.runOnMainSync{foregroundViewer()?.findViewById<ZoomImageView>(R.id.result_image)?.let{(it.drawable as? BitmapDrawable)?.bitmap?.let{bitmap->ref.set(bitmap)}}};return ref.get()}
    @Test fun uploadedImagePdfAndCanvasOpenFromTheirActualChatCards(){
        val api=ApiSession(context).apply{restore()};assertTrue("An existing user login is required",api.access.isNotBlank())
        val folder=File(context.cacheDir,"previews/device-chat-qa").apply{mkdirs()}
        val png=File(folder,"BitThink-photo-test.png")
        val bitmap=Bitmap.createBitmap(640,480,Bitmap.Config.ARGB_8888).apply{eraseColor(Color.rgb(33,160,206))}
        png.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)};bitmap.recycle()
        val pdfFile=File(folder,"BitThink-document-test.pdf")
        val pdf=PdfDocument();val page=pdf.startPage(PdfDocument.PageInfo.Builder(400,500,1).create())
        page.canvas.drawColor(Color.WHITE);val paint=Paint().apply{color=Color.BLACK;textSize=14f}
        repeat(12){page.canvas.drawText("Bit-Think Android document preview test line ${it+1}",20f,40f+it*28,paint)}
        pdf.finishPage(page);pdfFile.outputStream().use{pdf.writeTo(it)};pdf.close()
        val html=File(folder,"BitThink-slides-test.html").apply{writeText("""<!doctype html><html><head><style>body{background:#0c1012;color:white;font:32px sans-serif}.slide{padding:32px}</style></head><body><section class="slide">One</section><section class="slide">Two</section></body></html>""")}
        val cid=JSONObject(api.api("/conversations",JSONObject().put("title","Проверка результатов Android"))).getString("id")
        api.upload(png,png.name,"image/png",cid);api.upload(pdfFile,pdfFile.name,"application/pdf",cid);api.upload(html,html.name,"text/html",cid)
        val intent=JobNotifications.openIntent(context,cid)
        ActivityScenario.launch<MainActivity>(intent).use{scenario->
            val count=AtomicReference(0)
            waitFor{scenario.onActivity{a->count.set(a.findViewById<RecyclerView>(R.id.message_list)?.adapter?.itemCount?:0)};count.get()>=3}
            scenario.onActivity{it.findViewById<RecyclerView>(R.id.message_list).scrollToPosition(0)}
            val thumb=AtomicReference(false)
            waitFor{scenario.onActivity{a->thumb.set(views(a.window.decorView).filterIsInstance<android.widget.ImageView>().any{(it.drawable as? BitmapDrawable)?.bitmap!=null})};thumb.get()}
            scenario.onActivity{a->views(a.window.decorView).first{it.contentDescription?.toString()=="Открыть изображение"}.performClick()}
            waitFor{viewerBitmap()!=null}
            assertEquals(Color.rgb(33,160,206),viewerBitmap()!!.let{it.getPixel(it.width/2,it.height/2)})
            instrumentation.runOnMainSync{foregroundViewer()!!.finish()}
            waitFor{runCatching{scenario.state==androidx.lifecycle.Lifecycle.State.RESUMED}.getOrDefault(false)}
            scenario.onActivity{it.findViewById<RecyclerView>(R.id.message_list).scrollToPosition(1)}
            val pdfCard=AtomicReference<View>()
            waitFor{scenario.onActivity{a->views(a.window.decorView).firstOrNull{it.contentDescription?.toString()=="Открыть ${pdfFile.name}"}?.let{pdfCard.set(it)}};pdfCard.get()!=null}
            instrumentation.runOnMainSync{pdfCard.get().performClick()};waitFor{viewerBitmap()!=null}
            instrumentation.runOnMainSync{foregroundViewer()!!.finish()}
            waitFor{runCatching{scenario.state==androidx.lifecycle.Lifecycle.State.RESUMED}.getOrDefault(false)}
            scenario.onActivity{it.findViewById<RecyclerView>(R.id.message_list).scrollToPosition(2)}
            val canvasCard=AtomicReference<View>()
            waitFor{scenario.onActivity{a->views(a.window.decorView).firstOrNull{it.contentDescription?.toString()=="Открыть холст"}?.let{canvasCard.set(it)}};canvasCard.get()!=null}
            instrumentation.runOnMainSync{canvasCard.get().performClick()}
            val slides=AtomicReference<String>()
            waitFor{instrumentation.runOnMainSync{foregroundViewer()?.findViewById<WebView>(R.id.result_web)?.evaluateJavascript("document.querySelectorAll('.slide').length"){slides.set(it)}};slides.get()=="2"}
            instrumentation.runOnMainSync{foregroundViewer()!!.finish()}
            waitFor{runCatching{scenario.state==androidx.lifecycle.Lifecycle.State.RESUMED}.getOrDefault(false)}
        }
    }
}
