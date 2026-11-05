package space.bitsync.android

import android.animation.ValueAnimator
import android.content.Context
import android.content.Intent
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.text.Spanned
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import com.google.android.material.card.MaterialCardView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsAnimationCompat
import androidx.core.widget.doAfterTextChanged
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.transition.TransitionManager
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.progressindicator.LinearProgressIndicator
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import com.google.android.material.transition.MaterialFadeThrough
import io.noties.markwon.Markwon
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.Executors

/** Native Material UI; network and Markdown parsing never run on the main thread. */
class MainActivity : AppCompatActivity() {
    internal lateinit var api: ApiSession
    private val io = Executors.newSingleThreadExecutor()
    private val render = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private val markdown by lazy {
        Markwon.builder(this).usePlugin(object:io.noties.markwon.AbstractMarkwonPlugin(){
            override fun configureTheme(builder:io.noties.markwon.core.MarkwonTheme.Builder){
                builder.headingTextSizeMultipliers(floatArrayOf(1.375f,1.1875f,1.0625f,1f,1f,1f))
                    .headingTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL)).headingBreakHeight(0)
                    .linkColor(color(R.color.primary)).isLinkUnderlined(false)
                    .codeBackgroundColor(color(R.color.surface_variant)).codeBlockBackgroundColor(color(R.color.surface_variant))
            }
            override fun configureConfiguration(builder:io.noties.markwon.MarkwonConfiguration.Builder){
                builder.linkResolver { _,link ->
                    val result=ResultStore.forLink(link,"",cid)
                    if(result!=null)openResult(result)
                    else if(link.startsWith("https://")||link.startsWith("http://"))runCatching{startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(link)))}
                }
            }
        }).build()
    }
    private lateinit var host: FrameLayout
    internal lateinit var drawerLayout: androidx.drawerlayout.widget.DrawerLayout
    internal lateinit var drawerPanel: LinearLayout
    internal var drawerRequest = 0
    internal lateinit var content: LinearLayout
    private var composer: TextInputEditText? = null
    private var composerRow: View? = null
    private var send: MaterialButton? = null
    private var status: TextView? = null
    private var progress: LinearProgressIndicator? = null
    private var list: RecyclerView? = null
    private val rows = mutableListOf<MessageRow>()
    internal var selectedModel = ""
    internal var selectedModelName = "Экспресс"
    internal var modelButton: MaterialButton? = null
    internal var uploadBusy = false
    internal var saveCandidate: java.io.File? = null
    internal var searchSources = JSONArray()
    private var editingResult:NativeResult?=null
    private var permissionThenSubmit=false
    private val notificationPermission=registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        getSharedPreferences("notifications",0).edit().putBoolean("asked",true).apply()
        if(!granted)notice("Уведомления отключены. Ответ останется в беседе.")
        if(permissionThenSubmit){permissionThenSubmit=false;submit()}
    }
    private val resultViewer=registerForActivityResult(ActivityResultContracts.StartActivityForResult()){response->
        if(response.resultCode==RESULT_OK)response.data?.let{data->
            val prompt=data.getStringExtra("edit").orEmpty();val target=data.getStringExtra("conversation").orEmpty()
            if(prompt.isNotBlank()&&target.matches(Regex("[A-Za-z0-9_-]{1,64}"))) {
                val result=NativeResult(data.getStringExtra("source").orEmpty(),data.getStringExtra("name")?:"Результат",target)
                background {ui{if(cid!=target)selectConversation(target,"Bit-Think");editingResult=result;showChat(false);composer?.setText("Измени результат «${result.name}»: $prompt");composer?.requestFocus()}}
            }
        }
    }
    internal fun openResult(result:NativeResult){hideKeyboard();resultViewer.launch(ResultViewerActivity.intent(this,result))}
    private fun notificationSettings(){
        if(JobNotifications.allowed(this))notice("Уведомления о готовом результате включены")
        else if(android.os.Build.VERSION.SDK_INT>=33)notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        else startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName))
    }
    private val uploadPicker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null) handleUpload(uri) }
    private val savePicker = registerForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri ->
        if (uri != null) saveCandidate?.let { file ->
            background {
                contentResolver.openOutputStream(uri)?.use { output -> file.inputStream().use { it.copyTo(output) } } ?: error("Не удалось сохранить файл")
                ui { notice("Файл сохранён") }
            }
        }
    }
    internal fun chooseUpload() { if (!uploadBusy) uploadPicker.launch(arrayOf("*/*")) }
    internal fun chooseSave(file: java.io.File, name: String) { saveCandidate = file; savePicker.launch(name) }
    internal fun regenerate() {
        if(cid.isEmpty() || !ready || busy) { notice("Откройте завершённую беседу"); return }
        socket?.send(JSONObject().put("type","regenerate").put("payload",JSONObject().put("conversation_id",cid).put("request_id",UUID.randomUUID().toString())).toString())
    }
    private var adapter: MessagesAdapter? = null
    internal var cid = ""
    internal var title = "Bit-Think"
    private var page = "login"
    private var ready = false
    private var busy = false
    private var sending = false
    private var active = false
    private var socket: WebSocket? = null
    private var retryCount = 0
    private var epoch = 0
    private var historyVersion = 0
    private var historyLoading = false
    private var liveText = StringBuilder()
    private var liveId: String? = null
    private val liveSteps = mutableListOf<String>()
    private var streamScheduled = false
    private var followTail = true
    private var pending: Pending? = null
    private var backCallback: OnBackPressedCallback? = null
    private val drafts get() = getSharedPreferences("drafts", MODE_PRIVATE)

    data class Pending(val id: String, val cid: String, val text: String, var attempts: Int = 0, val model: String = "",val canvasTarget:String="",val notificationBaseline:ArrayList<String>?=null)
    internal data class MessageRow(val id: String, val role: String, var text: String, var rendered: Spanned? = null, val fileUrl: String? = null, val fileName: String? = null, var sources: JSONArray? = null, var steps: List<String> = emptyList(),var results:List<NativeResult> = emptyList())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        api = ApiSession(applicationContext)
        saveCandidate = savedInstanceState?.getString("saveFile")?.let { java.io.File(it) }?.takeIf {
            it.exists() && it.canonicalFile.parentFile == java.io.File(cacheDir,"exports").canonicalFile
        }
        cid = savedInstanceState?.getString("cid").orEmpty()
        intent.getStringExtra("open_conversation")?.takeIf{it.matches(Regex("[A-Za-z0-9_-]{1,64}"))}?.let{cid=it}
        savedInstanceState?.getString("editingSource")?.let{editingResult=NativeResult(it,savedInstanceState.getString("editingName")?:"Результат",cid)}
        title = savedInstanceState?.getString("title") ?: "Bit-Think"
        page = savedInstanceState?.getString("page") ?: "login"
        host = FrameLayout(this).apply { setBackgroundColor(color(R.color.surface)) }
        drawerLayout = androidx.drawerlayout.widget.DrawerLayout(this).apply {
            setScrimColor(0x99000000.toInt());drawerElevation=0f
        }
        drawerPanel = column().apply { setBackgroundColor(color(R.color.surface_variant)) }
        drawerLayout.addView(host,androidx.drawerlayout.widget.DrawerLayout.LayoutParams(-1,-1))
        val drawerWidth=minOf(dp(320),(resources.displayMetrics.widthPixels*.87f).toInt())
        drawerLayout.addView(drawerPanel,androidx.drawerlayout.widget.DrawerLayout.LayoutParams(drawerWidth,-1).apply{gravity=androidx.core.view.GravityCompat.START})
        drawerLayout.setDrawerLockMode(androidx.drawerlayout.widget.DrawerLayout.LOCK_MODE_LOCKED_CLOSED)
        drawerLayout.addDrawerListener(object:androidx.drawerlayout.widget.DrawerLayout.SimpleDrawerListener(){
            override fun onDrawerOpened(drawerView:View){backCallback?.isEnabled=true}
            override fun onDrawerClosed(drawerView:View){backCallback?.isEnabled=page!="chat"&&page!="login"}
        })
        ViewCompat.setOnApplyWindowInsetsListener(drawerPanel){v,insets->
            val bars=insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            v.setPadding(bars.left,bars.top,bars.right,bars.bottom);insets
        }
        setContentView(drawerLayout)
        ViewCompat.setOnApplyWindowInsetsListener(host) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            if (::content.isInitialized && v.width > 0) {
                val available = (v.width - bars.left - bars.right).coerceAtLeast(1)
                content.layoutParams = (content.layoutParams as FrameLayout.LayoutParams).apply { width = minOf(available, dp(840)) }
            }
            insets
        }
        ViewCompat.setWindowInsetsAnimationCallback(host, object : WindowInsetsAnimationCompat.Callback(DISPATCH_MODE_CONTINUE_ON_SUBTREE) {
            private var initialY = 0
            private var delta = 0f
            private var moving: View? = null
            override fun onPrepare(animation: WindowInsetsAnimationCompat) {
                if (animation.typeMask and WindowInsetsCompat.Type.ime() == 0) return
                moving = composerRow
                val location = IntArray(2); moving?.getLocationInWindow(location); initialY = location[1]
            }
            override fun onStart(animation: WindowInsetsAnimationCompat, bounds: WindowInsetsAnimationCompat.BoundsCompat): WindowInsetsAnimationCompat.BoundsCompat {
                if (animation.typeMask and WindowInsetsCompat.Type.ime() != 0 && ValueAnimator.areAnimatorsEnabled()) {
                    val location = IntArray(2); moving?.getLocationInWindow(location)
                    delta = (initialY - location[1]).toFloat(); moving?.translationY = delta
                }
                return bounds
            }
            override fun onProgress(insets: WindowInsetsCompat, runningAnimations: MutableList<WindowInsetsAnimationCompat>): WindowInsetsCompat {
                val ime = runningAnimations.firstOrNull { it.typeMask and WindowInsetsCompat.Type.ime() != 0 }
                if (ime != null && ValueAnimator.areAnimatorsEnabled()) moving?.translationY = delta * (1 - ime.interpolatedFraction)
                return insets
            }
            override fun onEnd(animation: WindowInsetsAnimationCompat) {
                if (animation.typeMask and WindowInsetsCompat.Type.ime() == 0) return
                moving?.translationY = 0f; moving = null; delta = 0f
            }
        })
        backCallback = object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() {
                if(drawerLayout.isDrawerOpen(androidx.core.view.GravityCompat.START))drawerLayout.closeDrawer(androidx.core.view.GravityCompat.START,ValueAnimator.areAnimatorsEnabled()) else showChat()
            }
        }.also { onBackPressedDispatcher.addCallback(this, it) }
        // Keystore can touch disk; let the system draw the first frame first.
        showLoading()
        background {
            api.restore()
            ui {
                if (api.access.isEmpty()) showLogin(false)
                else { if (page == "conversations") showConversations(false) else showChat(false); connect() }
            }
        }
    }

    internal fun color(id: Int) = ContextCompat.getColor(this, id)
    internal fun dp(value: Int) = (resources.displayMetrics.density * value).toInt()
    internal fun lp(width: Int = -1, height: Int = -2) = LinearLayout.LayoutParams(width, height)
    internal fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    internal fun label(value: String, appearance: Int, secondary: Boolean = false) = TextView(this).apply {
        text = value; setTextAppearance(appearance)
        setTextColor(color(if (secondary) R.color.on_surface_variant else R.color.on_surface))
    }
    internal fun body(value: String) = label(value, com.google.android.material.R.style.TextAppearance_Material3_BodyLarge, true)
    internal fun ui(task: () -> Unit) { runOnUiThread { if (!isDestroyed && !isFinishing) task() } }
    internal fun background(task: () -> Unit) {
        if (io.isShutdown) return
        io.execute { try { task() } catch (e: Exception) { ui { notice(e.message ?: "Не удалось подключиться. Повторите попытку.") } } }
    }
    internal fun notice(message: String) {
        Snackbar.make(host, message, Snackbar.LENGTH_LONG).setTextMaxLines(4).show()
    }
    private fun showLoading() {
        val loading = column().apply { gravity = Gravity.CENTER; setPadding(dp(24), dp(24), dp(24), dp(24)) }
        loading.addView(label("Bit-Think", com.google.android.material.R.style.TextAppearance_Material3_HeadlineMedium))
        loading.addView(LinearProgressIndicator(this).apply { isIndeterminate = true }, lp(dp(160), dp(4)).apply { topMargin = dp(24) })
        host.addView(loading, FrameLayout.LayoutParams(-1, -1))
    }
    internal fun screen(name: String, animate: Boolean) {
        composerRow?.translationY = 0f
        composer = null; composerRow = null; send = null; status = null; progress = null; list = null; adapter = null
        page = name
        drawerLayout.setDrawerLockMode(if(name=="chat")androidx.drawerlayout.widget.DrawerLayout.LOCK_MODE_UNLOCKED else androidx.drawerlayout.widget.DrawerLayout.LOCK_MODE_LOCKED_CLOSED)
        TransitionManager.endTransitions(host)
        if (animate && ValueAnimator.areAnimatorsEnabled() && host.isLaidOut) {
            // Fade-through explains screen replacement; never animate tokens/history rows.
            TransitionManager.beginDelayedTransition(host, MaterialFadeThrough().apply { duration = 180L })
        }
        host.removeAllViews(); content = column()
        val width = minOf(resources.displayMetrics.widthPixels, dp(840))
        host.addView(content, FrameLayout.LayoutParams(width, -1, Gravity.CENTER_HORIZONTAL))
        ViewCompat.requestApplyInsets(host)
        backCallback?.isEnabled = name != "login" && name != "chat"
    }
    internal fun toolbar(value: String, back: Boolean = false): MaterialToolbar {
        return MaterialToolbar(this).apply {
            title = value; setTitleTextColor(color(R.color.on_surface)); minimumHeight = dp(64)
            setBackgroundColor(color(R.color.surface))
            setNavigationIcon(if (back) R.drawable.ic_back else R.drawable.ic_menu)
            setNavigationIconTint(color(R.color.on_surface))
            navigationContentDescription = if (back) "Вернуться в чат" else "Открыть беседы"
            setNavigationOnClickListener { hideKeyboard(); if (back) showChat() else showConversations() }
        }.also { content.addView(it, lp()) }
    }
    internal fun filledButton(value: String, action: () -> Unit) = MaterialButton(this).apply {
        text = value; minHeight = dp(56); setOnClickListener { action() }
    }
    internal fun textButton(value: String, action: () -> Unit) = MaterialButton(this, null, com.google.android.material.R.attr.borderlessButtonStyle).apply {
        text = value; minHeight = dp(48); setOnClickListener { action() }
    }
    internal fun field(value: String, idValue: Int, type: Int): Pair<TextInputLayout, TextInputEditText> {
        val layout = TextInputLayout(this, null, com.google.android.material.R.attr.textInputOutlinedStyle).apply { hint = value }
        val edit = TextInputEditText(layout.context).apply {
            id = idValue; inputType = type; minHeight = dp(56); setSingleLine(true)
            setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyLarge)
        }
        layout.addView(edit, lp())
        return layout to edit
    }
    private fun showLogin(animate: Boolean = true) {
        screen("login", animate)
        val scroller = ScrollView(this).apply { isFillViewport = true }
        val form = column().apply { setPadding(dp(24), dp(40), dp(24), dp(24)); gravity = Gravity.CENTER_VERTICAL }
        form.addView(label("Bit-Think", com.google.android.material.R.style.TextAppearance_Material3_HeadlineLarge))
        form.addView(body("Войдите, чтобы продолжить свои беседы."), lp().apply { topMargin = dp(12); bottomMargin = dp(32) })
        val (emailBox, email) = field("Электронная почта", R.id.email, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS)
        val (passwordBox, password) = field("Пароль", R.id.password, InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        email.setAutofillHints(View.AUTOFILL_HINT_USERNAME); password.setAutofillHints(View.AUTOFILL_HINT_PASSWORD)
        email.imeOptions = EditorInfo.IME_ACTION_NEXT; password.imeOptions = EditorInfo.IME_ACTION_DONE
        passwordBox.endIconMode = TextInputLayout.END_ICON_PASSWORD_TOGGLE
        form.addView(emailBox, lp().apply { bottomMargin = dp(16) })
        form.addView(passwordBox, lp().apply { bottomMargin = dp(20) })
        val error = body("").apply { setTextColor(color(R.color.error)); visibility = View.GONE; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        form.addView(error, lp())
        val loginProgress = LinearProgressIndicator(this).apply { isIndeterminate = true; visibility = View.INVISIBLE }
        lateinit var login: MaterialButton
        val attempt = {
            emailBox.error = if (email.text.isNullOrBlank()) "Введите почту" else null
            passwordBox.error = if (password.text.isNullOrBlank()) "Введите пароль" else null
            if (emailBox.error == null && passwordBox.error == null && login.isEnabled) {
                val address = email.text.toString().trim(); val secret = password.text.toString()
                login.isEnabled = false; login.text = "Входим…"; loginProgress.visibility = View.VISIBLE; error.visibility = View.GONE
                hideKeyboard()
                background {
                    try { api.login(address, secret); ui { showChat(); connect() } }
                    catch (e: Exception) { ui { error.text = e.message ?: "Не удалось войти"; error.visibility = View.VISIBLE } }
                    finally { ui { login.isEnabled = true; login.text = "Войти"; loginProgress.visibility = View.INVISIBLE } }
                }
            }
        }
        login = filledButton("Войти", attempt); form.addView(login, lp())
        form.addView(loginProgress, lp(-1, dp(4)).apply { topMargin = dp(8) })
        form.addView(textButton("Конфиденциальность") { openPrivacy() }, lp().apply { topMargin = dp(12) })
        password.setOnEditorActionListener { _, action, _ -> if (action == EditorInfo.IME_ACTION_DONE) { attempt(); true } else false }
        email.doAfterTextChanged { emailBox.error = null }; password.doAfterTextChanged { passwordBox.error = null }
        scroller.addView(form, ViewGroup.LayoutParams(-1, -1)); content.addView(scroller, lp(-1, -1))
    }

    internal fun showChat(animate: Boolean = true) {
        screen("chat", animate)
        toolbar("Bit-Think").apply {
            logo = ContextCompat.getDrawable(this@MainActivity, R.drawable.ic_brand)
            menu.add("Новая беседа").setIcon(R.drawable.ic_add).setShowAsAction(android.view.MenuItem.SHOW_AS_ACTION_IF_ROOM)
            menu.add("Холст результатов");menu.add("Уведомления")
            listOf("Режим ответа","Файлы беседы","Профиль и тариф","Память","Инструкции","Корзина","Повторить ответ").forEach { menu.add(it) }; menu.add("Обновить подключение"); menu.add("Конфиденциальность"); menu.add("Выйти")
            setOnMenuItemClickListener { item ->
                when (item.title.toString()) {
                    "Холст результатов" -> showCanvasResults()
                    "Уведомления" -> notificationSettings()
                    "Режим ответа" -> showModels()
                    "Файлы беседы" -> showFiles()
                    "Профиль и тариф" -> showProfile()
                    "Память" -> showMemory()
                    "Инструкции" -> showInstructions()
                    "Корзина" -> showTrash()
                    "Повторить ответ" -> regenerate()
                    "Новая беседа" -> selectConversation("", "Bit-Think")
                    "Обновить подключение" -> { connect(); if (cid.isNotEmpty()) loadHistory() }
                    "Конфиденциальность" -> openPrivacy()
                    "Выйти" -> confirmLogout()
                }; true
            }
        }
        status = label(if (ready) "" else "Подключение…", com.google.android.material.R.style.TextAppearance_Material3_LabelMedium, true).apply {
            setPadding(dp(24), dp(4), dp(24), dp(8))
        }.also { content.addView(it, lp()) }
        progress = null
        status?.visibility=View.GONE
        list = RecyclerView(this).apply {
            id = R.id.message_list; layoutManager = LinearLayoutManager(this@MainActivity)
            itemAnimator = null // Repeated token updates must not start change animations.
            clipToPadding = false; setPadding(dp(24), dp(12), dp(24), dp(16))
            addOnScrollListener(object : RecyclerView.OnScrollListener() {
                override fun onScrolled(rv: RecyclerView, dx: Int, dy: Int) {
                    if (rv.scrollState == RecyclerView.SCROLL_STATE_IDLE) return
                    if (dy < 0) followTail = false
                    if (!rv.canScrollVertically(1)) followTail = true
                }
            })
        }.also { content.addView(it, lp(-1, 0).apply { weight = 1f }) }
        adapter = MessagesAdapter().also { list!!.adapter = it }
        val row = column().apply { setPadding(dp(16), dp(8), dp(16), dp(12)) }
        composerRow = row
        val card = MaterialCardView(this).apply {
            radius = dp(20).toFloat(); cardElevation = 0f
            setCardBackgroundColor(color(R.color.surface_variant)); strokeWidth = 0
        }
        val inputGroup = column().apply { setPadding(dp(12),dp(8),dp(12),dp(8)) }
        editingResult?.takeIf{it.conversation==cid}?.let { result ->
            inputGroup.addView(textButton("Правка: ${result.name} · отменить"){editingResult=null;saveDraft();showChat(false)}.apply{maxLines=1;ellipsize=android.text.TextUtils.TruncateAt.END},lp())
        }
        val edit = TextInputEditText(this).apply {
            id = R.id.composer; background = null
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            minHeight=dp(56); setPadding(dp(4),dp(12),dp(4),dp(12))
            setTextAppearance(com.google.android.material.R.style.TextAppearance_Material3_BodyLarge)
        }
        edit.apply {
            hint = "Спросите что угодно"; setSingleLine(false); maxLines = 5
            imeOptions = EditorInfo.IME_FLAG_NO_ENTER_ACTION
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            setText(drafts.getString(cid, "")); doAfterTextChanged { updateSend() }
        }
        composer = edit
        inputGroup.addView(edit, lp())
        val actions = LinearLayout(this).apply { gravity=Gravity.CENTER_VERTICAL }
        actions.addView(textButton("") { chooseUpload() }.apply {
            icon=ContextCompat.getDrawable(this@MainActivity,R.drawable.ic_attach)
            iconPadding=0;iconGravity=MaterialButton.ICON_GRAVITY_TEXT_START
            minimumWidth=dp(48);minWidth=dp(48);setPadding(dp(12),0,dp(12),0)
            contentDescription="Прикрепить файл или фото"
        }, lp(dp(48),dp(48)))
        modelButton = textButton(selectedModelName) { showModels() }.apply {
            maxLines=1;ellipsize=android.text.TextUtils.TruncateAt.END;setPadding(dp(8),0,dp(8),0)
        }.also { actions.addView(it, lp(0,dp(48)).apply{weight=1f}) }
        send = MaterialButton(this, null, com.google.android.material.R.attr.materialIconButtonFilledStyle).apply {
            icon = ContextCompat.getDrawable(this@MainActivity, if (busy) R.drawable.ic_stop else R.drawable.ic_send)
            iconGravity = MaterialButton.ICON_GRAVITY_TEXT_START; iconPadding = 0; text = ""
            contentDescription = if (busy) "Остановить ответ" else "Отправить сообщение"
            minWidth = dp(48); minimumWidth = dp(48); minHeight = dp(56)
            setOnClickListener { if (busy) stopAnswer() else submit() }
        }.also { actions.addView(it, lp(dp(48), dp(48))) }
        inputGroup.addView(actions,lp()); card.addView(inputGroup); row.addView(card,lp())
        content.addView(row, lp())
        if (cid.isEmpty()) welcome() else { rows.clear(); adapter?.notifyDataSetChanged(); loadHistory() }
        updateSend()
        if(api.access.isNotEmpty()) background { runCatching { JSONObject(api.api("/models")) }.getOrNull()?.let { models -> ui {
            selectedModel = models.optString("selected"); selectedModelName = models.optString("selectedName","Экспресс"); modelButton?.text=selectedModelName
        } } }
    }
    private fun welcome() {
        busy = false; historyLoading = false; liveId = null; liveText.clear(); rows.clear();searchSources=JSONArray()
        rows.add(MessageRow("welcome", "welcome", "С чего начнём?"))
        rows.add(MessageRow("welcome-hint", "hint", "Задайте вопрос, прикрепите файл или продолжите беседу."))
        adapter?.notifyDataSetChanged(); updateSend()
    }
    internal fun selectConversation(id: String, name: String) {
        drawerLayout.closeDrawer(androidx.core.view.GravityCompat.START,ValueAnimator.areAnimatorsEnabled())
        saveDraft(); historyVersion++; cid = id; title = name; busy = false; sending = false
        pending = null; liveId = null; liveText.clear();searchSources=JSONArray();editingResult=null; followTail = true; hideKeyboard(); showChat()
    }
    internal fun showConversations(animate: Boolean = true) {
        saveDraft();hideKeyboard();fillConversationDrawer()
        drawerLayout.openDrawer(androidx.core.view.GravityCompat.START,animate && ValueAnimator.areAnimatorsEnabled())
    }
    private fun confirmLogout() {
        MaterialAlertDialogBuilder(this).setTitle("Выйти из аккаунта?").setMessage("История останется в вашем аккаунте.")
            .setNegativeButton("Отмена", null).setPositiveButton("Выйти") { _, _ ->
                disconnect();JobNotifications.stop(this);ResultStore.workers.execute{ResultStore.clear(applicationContext)}; api.logout(); drafts.edit().clear().apply(); cid = ""; pending = null; rows.clear();editingResult=null; showLogin()
            }.show()
    }
    private fun openPrivacy() {
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://bit-think.space/privacy"))) }.onFailure { notice("Не удалось открыть браузер") }
    }
    internal fun hideKeyboard() {
        (getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager).hideSoftInputFromWindow(host.windowToken, 0)
        composer?.clearFocus()
    }
    private fun saveDraft() { if (page == "chat") composer?.let { drafts.edit().putString(cid, it.text.toString()).apply() } }
    internal fun updateSend() {
        send?.apply {
            isEnabled = ready && !sending && !historyLoading && !uploadBusy && (busy || !composer?.text.isNullOrBlank())
            icon = ContextCompat.getDrawable(this@MainActivity, if (busy) R.drawable.ic_stop else R.drawable.ic_send)
            contentDescription = if (busy) "Остановить ответ" else "Отправить сообщение"
        }
        progress?.visibility = if (busy || sending) View.VISIBLE else View.INVISIBLE
    }
    private fun setStatus(value: String) {
        val quiet=value=="На связи" || value.isBlank()
        status?.visibility=if(quiet||busy||sending)View.GONE else View.VISIBLE
        status?.text=if(quiet)"" else value
        if((busy||sending)&&liveId!=null) {
            if(value !in listOf("Печатает…","На связи") && value.isNotBlank() && liveSteps.lastOrNull()!=value) { liveSteps.add(value);if(liveSteps.size>24)liveSteps.removeAt(0) }
            val index=rows.indexOfFirst{it.id==liveId}
            if(index<0 && liveText.isEmpty()) {rows.add(MessageRow(liveId!!,"status",value));adapter?.notifyItemInserted(rows.lastIndex);scrollToEnd()}
            else if(index>=0 && rows[index].role=="status") {rows[index].text=value;adapter?.notifyItemChanged(index,"state")}
        }
        updateSend()
    }
    private fun scrollToEnd() { if (followTail && rows.isNotEmpty()) list?.post { if (followTail && rows.isNotEmpty()) list?.scrollToPosition(rows.lastIndex) } }
    internal fun loadHistory() {
        if (cid.isEmpty()) return
        historyLoading = true; updateSend()
        val requested = cid; val version = ++historyVersion
        background {
          try {
            val json = JSONArray(api.api("/conversations/$requested/messages"))
            val history = (0 until json.length()).map { i ->
                val m = json.getJSONObject(i); val raw = m.optString("content")
                val attachment=m.optJSONObject("attachment")
                val refs=ResultStore.extract(raw,attachment,requested)
                val text=if(refs.any{it.name==raw.trim()})"" else ResultStore.displayText(raw)
                MessageRow(m.optString("id", "$i"), m.optString("role"), text,
                    if (m.optString("role") == "assistant") markdown.toMarkdown(text) else null,
                    attachment?.optString("original_url")?.ifBlank{attachment.optString("url")},attachment?.optString("name"),m.optJSONArray("search"),results=refs)
            }
            ui {
                if (page != "chat" || cid != requested || version != historyVersion) return@ui
                rows.clear(); rows.addAll(history)
                if (busy && liveId != null) rows.add(MessageRow(liveId!!, if(liveText.isEmpty())"status" else "assistant",
                    if(liveText.isEmpty())liveSteps.lastOrNull()?:"Готовим ответ…" else liveText.toString(),sources=searchSources))
                historyLoading = false; updateSend(); adapter?.notifyDataSetChanged(); scrollToEnd()
            }
          } catch (e: Exception) {
            ui {
                if (cid == requested && version == historyVersion) {
                    historyLoading = false; setStatus("История не загрузилась · обновить в меню")
                    notice(e.message ?: "Проверьте подключение")
                }
            }
          }
        }
    }
    private fun submit() {
        val text = composer?.text.toString().trim()
        if (text.isEmpty() || !ready || busy || sending || historyLoading || uploadBusy) return
        if(android.os.Build.VERSION.SDK_INT>=33&&!getSharedPreferences("notifications",0).getBoolean("asked",false)&&!JobNotifications.allowed(this)){
            permissionThenSubmit=true;notificationPermission.launch(android.Manifest.permission.POST_NOTIFICATIONS);return
        }
        sending = true; updateSend(); setStatus("Отправляем…")
        val original = cid; val currentEpoch = epoch
        background {
            try {
                val target = if (original.isEmpty()) JSONObject(api.api("/conversations", JSONObject())).getString("id") else original
                val notificationBaseline=if(JobNotifications.allowed(this))runCatching{JobNotifications.baseline(api,target)}.getOrNull()else null
                ui {
                    if (page != "chat" || cid != original || currentEpoch != epoch || !ready) { sending = false; updateSend(); return@ui }
                    cid = target; backCallback?.isEnabled = false
                    val operation = Pending(UUID.randomUUID().toString(), target, text, model=selectedModel,
                        canvasTarget=editingResult?.source?.takeIf{it.startsWith("/uploads/")||it.startsWith("/conversations/")||it.startsWith("https://bit-think.space/")}.orEmpty(),notificationBaseline=notificationBaseline)
                    pending = operation; drafts.edit().putString(target, text).remove("").apply(); sendPending(operation)
                }
            } catch (e: Exception) { ui { sending = false; setStatus("Сообщение не отправлено"); notice(e.message ?: "Повторите попытку") } }
        }
    }
    private fun sendPending(operation: Pending) {
        if(operation.attempts==0)JobNotifications.prepare(this,operation.cid,operation.notificationBaseline)
        operation.attempts++
        val payload = JSONObject().apply { if (operation.model.isNotEmpty()) put("model",operation.model);if(operation.canvasTarget.isNotBlank())put("canvas_target",operation.canvasTarget) }.put("conversation_id", operation.cid).put("content", operation.text).put("request_id", operation.id)
        if (socket?.send(JSONObject().put("type", "message").put("payload", payload).toString()) != true) {
            JobNotifications.cancel(this,operation.cid);sending = false; setStatus("Нет подключения · текст сохранён"); return
        }
        main.postDelayed({ if (pending?.id == operation.id && sending) { setStatus("Проверяем доставку…"); connect() } }, 15000)
    }
    private fun accepted(operation: Pending) {
        historyVersion++
        pending = null; sending = false; busy = true; followTail = true;editingResult=null
        if (composer?.text.toString().trim() == operation.text) composer?.setText("")
        drafts.edit().remove(operation.cid).apply()
        if (rows.firstOrNull()?.role == "welcome") rows.clear()
        rows.add(MessageRow(operation.id, "user", operation.text)); adapter?.notifyDataSetChanged()
        liveId = "live-${operation.id}"; liveText.clear();liveSteps.clear();searchSources=JSONArray(); setStatus("Готовим ответ…"); scrollToEnd()
    }
    private fun stopAnswer() {
        if (ready && busy) {
            socket?.send(JSONObject().put("type", "stop").put("payload", JSONObject().put("conversation_id", cid)).toString())
            setStatus("Останавливаем…")
        }
    }
    private fun connect() {
        if (!active || api.access.isEmpty()) return
        val connection = ++epoch
        socket?.cancel(); socket = null; ready = false; updateSend()
        background {
            try {
                api.api("/auth/me")
                ui {
                    if (!active || connection != epoch || api.access.isEmpty()) return@ui
                    socket = api.http.newWebSocket(Request.Builder().url(ApiSession.WS_URL).build(), object : WebSocketListener() {
                        override fun onOpen(webSocket: WebSocket, response: Response) {
                            webSocket.send(JSONObject().put("type", "auth").put("payload", JSONObject().put("token", api.access)).toString())
                        }
                        override fun onMessage(webSocket: WebSocket, text: String) {
                            val message = runCatching { JSONObject(text) }.getOrNull() ?: return
                            ui { if (connection == epoch && active) event(message) }
                        }
                        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                            if(response?.code in listOf(401,403,404)) ui {
                                if(connection==epoch){disconnect();setStatus("Соединение отклонено сервером");notice("Сервер отклонил соединение (${response?.code}). Повторите вход или обновите подключение в меню.")}
                            } else lost(connection)
                        }
                        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { lost(connection) }
                    })
                }
            } catch (e: Exception) {
                ui {
                    if (connection == epoch) {
                        if(e is ApiException && e.status in listOf(401,403)) {
                            disconnect();api.logout();showLogin();notice("Сессия истекла. Войдите снова.")
                        } else { setStatus("Нет подключения · повторить в меню"); lost(connection) }
                    }
                }
            }
        }
    }
    private fun lost(connection: Int) {
        ui {
            if (!active || connection != epoch) return@ui
            ready = false; setStatus("Переподключаемся…")
            val delay = minOf(30000L, 1000L shl minOf(retryCount++, 5))
            main.postDelayed({ if (active && connection == epoch) connect() }, delay)
        }
    }
    private fun disconnect() { epoch++; ready = false; socket?.cancel(); socket = null; updateSend() }
    private fun event(event: JSONObject) {
        val type = event.optString("type"); val p = event.optJSONObject("payload") ?: JSONObject()
        if(type=="accepted")JobNotifications.bind(this,p.optString("conversation_id"),p.optString("generation_id"))
        if (type == "jobs") {
            ready = true; busy = false; retryCount = 0
            val jobs = p.optJSONArray("jobs") ?: JSONArray()
            for (i in 0 until jobs.length()) {
                val job = jobs.getJSONObject(i)
                if (cid.isNotEmpty() && job.optString("conversation_id") == cid) {
                    busy = job.isNull("error") || job.optString("error").isBlank()
                    liveId = "live-$cid"; liveText = StringBuilder(job.optString("text"));searchSources=job.optJSONArray("search")?:JSONArray(); renderStream()
                    setStatus(job.optString("status_text").ifBlank { "Готовим ответ…" })
                }
            }
            val retry = pending
            if (retry != null) sendPending(retry) else { sending = false; if (!busy) setStatus("На связи") }
            if (cid.isNotEmpty() && page == "chat") loadHistory()
            updateSend(); return
        }
        if (p.optString("conversation_id").let { it.isNotEmpty() && it != cid }) return
        when (type) {
            "accepted" -> pending?.takeIf { it.id == p.optString("request_id") }?.let { operation ->
                if (operation.attempts <= 1) accepted(operation)
                else {
                    pending = null; sending = false
                    if (composer?.text.toString().trim() == operation.text) composer?.setText("")
                    drafts.edit().remove(operation.cid).apply()
                    busy = p.optString("status") in setOf("queued", "running", "external")
                    if (!busy) { liveId = null; liveText.clear() }
                    setStatus(if (busy) "Готовим ответ…" else "На связи"); loadHistory()
                }
            }
            "thinking" -> { busy = true; setStatus("Готовим ответ…") }
            "status" -> setStatus(p.optString("text"))
            "extras" -> { searchSources=p.optJSONArray("search")?:JSONArray();rows.lastOrNull{it.id==liveId}?.sources=searchSources }
            "chunk" -> {
                busy = true; if (liveId == null) liveId = "live-$cid"
                liveText.append(p.optString("text")); scheduleStream(); setStatus("Печатает…")
            }
            "done", "stopped" -> {
                busy = false; sending = false; pending = null
                renderStream(); finalizeMarkdown()
                val empty=rows.indexOfFirst{it.id==liveId && it.role=="status"}
                if(empty>=0){rows.removeAt(empty);adapter?.notifyItemRemoved(empty)}
                liveId = null; liveText.clear()
                setStatus(if (type == "stopped") "Ответ остановлен" else "На связи")
                status?.announceForAccessibility(if (type == "stopped") "Ответ остановлен" else "Ответ готов")
            }
            "error" -> {
                if (p.optString("request_id") == pending?.id) { JobNotifications.cancel(this,cid);pending = null; sending = false }
                busy = false; setStatus("Не удалось выполнить запрос"); notice(p.optString("message", "Повторите попытку"))
            }
            "file" -> {
                val conversation=cid;val name=p.optString("filename","Результат");val source=p.optString("url");val encoded=p.optString("data")
                fun append(url:String){
                    if(conversation!=cid)return
                    val result=NativeResult(url,name,conversation)
                    rows.add(MessageRow(UUID.randomUUID().toString(),"file","",fileUrl=url,fileName=name,results=listOf(result)))
                    adapter?.notifyItemInserted(rows.lastIndex);scrollToEnd()
                }
                if(ResultStore.validSource(source))append(source)
                else if(encoded.isNotBlank())background{val local=ResultStore.fromBase64(applicationContext,encoded,name);ui{append(local)}}
                else append("conversation-file:$conversation/$name")
            }
        }
    }
    private fun scheduleStream() {
        if (streamScheduled) return
        streamScheduled = true
        // Coalesce bursty events; do not parse or animate Markdown for each token.
        main.postDelayed({ streamScheduled = false; if (page == "chat") renderStream() }, 80)
    }
    private fun renderStream() {
        val id = liveId ?: return
        if (page != "chat" || liveText.isEmpty()) return
        val existing = rows.indexOfFirst { it.id == id }
        if (existing >= 0) {
            if(rows[existing].role=="status") rows[existing]=MessageRow(id,"assistant",liveText.toString(),sources=searchSources)
            else {rows[existing].text=liveText.toString();rows[existing].rendered=null}
            adapter?.notifyItemChanged(existing,"stream")
        }
        else { rows.add(MessageRow(id, "assistant", liveText.toString(),sources=searchSources)); adapter?.notifyItemInserted(rows.lastIndex) }
        scrollToEnd()
    }
    private fun finalizeMarkdown() {
        val row = rows.lastOrNull { it.role == "assistant" && it.id==liveId } ?: return
        row.steps=liveSteps.toList()
        val snapshot = row.text
        render.execute {
            val refs=ResultStore.extract(snapshot,null,cid);val display=ResultStore.displayText(snapshot)
            val styled = markdown.toMarkdown(display)
            ui { val index = rows.indexOfFirst { it === row && it.text == snapshot }; if (index >= 0) { row.text=display;row.results=(row.results+refs).distinctBy{it.source};row.rendered = styled; adapter?.notifyItemChanged(index, "final") } }
        }
    }

    private inner class MessageHolder(val group: LinearLayout, val author: TextView, val text: TextView,
        val actions: MaterialButton,val strip:LinearLayout,val spinner:com.google.android.material.progressindicator.CircularProgressIndicator,
        val copy:MaterialButton,val share:MaterialButton,val results:LinearLayout) : RecyclerView.ViewHolder(group) {var role="";var resultKey=""}
    private inner class MessagesAdapter : RecyclerView.Adapter<MessageHolder>() {
        override fun getItemCount() = rows.size
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): MessageHolder {
            val group = column().apply { setPadding(0, dp(12), 0, dp(16)); layoutParams = RecyclerView.LayoutParams(-1, -2) }
            val author = label("", com.google.android.material.R.style.TextAppearance_Material3_LabelMedium, true)
            val byline=LinearLayout(this@MainActivity).apply{gravity=Gravity.CENTER_VERTICAL}
            val spinner=com.google.android.material.progressindicator.CircularProgressIndicator(this@MainActivity).apply{
                isIndeterminate=true;indicatorSize=dp(14);trackThickness=dp(2);indicatorInset=0;setIndicatorColor(color(R.color.primary))
                importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO
            }
            byline.addView(author,lp(-2,-2));byline.addView(spinner,lp(dp(16),dp(16)).apply{marginStart=dp(8)})
            val text = label("", com.google.android.material.R.style.TextAppearance_Material3_BodyLarge).apply {
                setTextIsSelectable(true); setLineSpacing(dp(4).toFloat(), 1.06f); setLinkTextColor(color(R.color.primary)); linksClickable = true
            }
            group.addView(byline, lp().apply { bottomMargin = dp(8) }); group.addView(text, lp())
            val results=column();group.addView(results,lp())
            fun action(iconId:Int,description:String)=textButton(""){}.apply{
                icon=ContextCompat.getDrawable(this@MainActivity,iconId);iconPadding=0;iconGravity=MaterialButton.ICON_GRAVITY_TEXT_START
                minWidth=dp(48);minimumWidth=dp(48);minHeight=dp(48);setPadding(dp(14),0,dp(14),0);iconSize=dp(18)
                iconTint=android.content.res.ColorStateList.valueOf(color(R.color.on_surface_variant));contentDescription=description
            }
            val actions=action(R.drawable.ic_reply_more,"Действия с ответом")
            val copy=action(R.drawable.ic_reply_copy,"Скопировать ответ")
            val share=action(R.drawable.ic_reply_share,"Поделиться ответом")
            val strip=LinearLayout(this@MainActivity).apply{gravity=Gravity.START}
            strip.addView(copy,lp(dp(48),dp(48)));strip.addView(actions,lp(dp(48),dp(48)))
            group.addView(strip,lp().apply{topMargin=dp(4)})
            return MessageHolder(group, author, text, actions,strip,spinner,copy,share,results)
        }
        override fun onBindViewHolder(holder: MessageHolder, position: Int) {
            val row = rows[position]
            holder.role=row.role
            holder.author.text = "Готовлю ответ…"
            holder.author.visibility = if(row.role=="status")View.VISIBLE else View.GONE
            (holder.author.parent as View).visibility=if(row.role=="status")View.VISIBLE else View.GONE
            holder.text.setTextAppearance(if (row.role == "user" || row.role == "welcome") com.google.android.material.R.style.TextAppearance_Material3_TitleLarge else com.google.android.material.R.style.TextAppearance_Material3_BodyLarge)
            holder.text.typeface = Typeface.create("sans-serif",Typeface.NORMAL)
            holder.text.includeFontPadding=true
            holder.text.textSize=when(row.role){"welcome"->24f;"user"->15f;"status"->13f;else->16f}
            holder.text.visibility=if(row.role=="status"||row.text.isBlank())View.GONE else View.VISIBLE
            holder.resultKey=row.results.joinToString("|"){it.source};bindResultCards(holder.results,row.results)
            val bubble=row.role=="user"
            val textLayout=holder.text.layoutParams as LinearLayout.LayoutParams
            textLayout.width=if(bubble)ViewGroup.LayoutParams.WRAP_CONTENT else ViewGroup.LayoutParams.MATCH_PARENT
            textLayout.gravity=if(bubble)Gravity.END else Gravity.START
            holder.text.layoutParams=textLayout
            holder.text.maxWidth=if(bubble)((minOf(resources.displayMetrics.widthPixels,dp(840))-dp(48))*.88f).toInt() else Int.MAX_VALUE
            holder.text.setPadding(if(bubble)dp(14) else 0,if(bubble)dp(9) else 0,if(bubble)dp(14) else 0,if(bubble)dp(9) else 0)
            holder.text.background=if(bubble)android.graphics.drawable.GradientDrawable().apply{setColor(color(R.color.message_paper));cornerRadius=dp(18).toFloat()}else null
            holder.text.setLineSpacing(dp(if(bubble)1 else 2).toFloat(),if(bubble)1.15f else 1.3f)
            holder.text.setTextColor(color(if(row.role=="status"||row.role=="hint")R.color.on_surface_variant else R.color.on_surface))
            holder.text.maxLines=if(row.role=="status")3 else Int.MAX_VALUE
            holder.spinner.visibility=if(row.role=="status")View.VISIBLE else View.GONE
            val latest=rows.lastOrNull{it.role=="assistant"}===row
            holder.strip.visibility=if((row.role=="file"||(row.role=="assistant"&&latest))&&!(row.id==liveId&&busy))View.VISIBLE else View.GONE
            holder.actions.setOnClickListener { messageActions(row) }
            holder.copy.setOnClickListener{(getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager).setPrimaryClip(android.content.ClipData.newPlainText("Bit-Think",row.text))}
            holder.share.setOnClickListener{startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,row.text),"Поделиться ответом"))}
            if (row.rendered != null) markdown.setParsedMarkdown(holder.text, row.rendered!!) else holder.text.text = row.text
        }
        override fun onBindViewHolder(holder: MessageHolder, position: Int, payloads: MutableList<Any>) {
            if (payloads.isNotEmpty()) {
                val row = rows[position]
                if(holder.role!=row.role){onBindViewHolder(holder,position);return}
                val resultKey=row.results.joinToString("|"){it.source}
                if(holder.resultKey!=resultKey){holder.resultKey=resultKey;bindResultCards(holder.results,row.results)}
                holder.text.visibility=if(row.role=="status"||row.text.isBlank())View.GONE else View.VISIBLE
                holder.spinner.visibility=if(row.role=="status")View.VISIBLE else View.GONE
                val latest=rows.lastOrNull{it.role=="assistant"}===row
                holder.strip.visibility=if((row.role=="file"||(row.role=="assistant"&&latest))&&!(row.id==liveId&&busy))View.VISIBLE else View.GONE
                if (row.rendered != null) markdown.setParsedMarkdown(holder.text, row.rendered!!) else holder.text.text = row.text
            } else super.onBindViewHolder(holder, position, payloads)
        }
    }
    private inner class ConversationsAdapter(private val entries: List<JSONObject>) : RecyclerView.Adapter<ConversationHolder>() {
        override fun getItemCount() = entries.size
        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ConversationHolder {
            val label = label("", com.google.android.material.R.style.TextAppearance_Material3_TitleMedium).apply {
                minHeight = dp(64); gravity = Gravity.CENTER_VERTICAL; setPadding(dp(24), dp(12), dp(24), dp(12)); isClickable = true; isFocusable = true
                val typed = android.util.TypedValue(); theme.resolveAttribute(android.R.attr.selectableItemBackground, typed, true); setBackgroundResource(typed.resourceId)
                layoutParams = RecyclerView.LayoutParams(-1, -2)
            }
            return ConversationHolder(label)
        }
        override fun onBindViewHolder(holder: ConversationHolder, position: Int) {
            val entry = entries[position]; val name = entry.optString("title").ifBlank { "Беседа" }
            holder.label.text = name
            ViewCompat.setAccessibilityDelegate(holder.label, object : androidx.core.view.AccessibilityDelegateCompat() {
                override fun onInitializeAccessibilityNodeInfo(host: View, info: androidx.core.view.accessibility.AccessibilityNodeInfoCompat) {
                    super.onInitializeAccessibilityNodeInfo(host, info); info.className = "android.widget.Button"
                }
            })
            holder.label.setOnClickListener { selectConversation(entry.getString("id"), name) }
            holder.label.setOnLongClickListener { conversationActions(entry.getString("id"),name); true }
        }
    }
    private class ConversationHolder(val label: TextView) : RecyclerView.ViewHolder(label)

    override fun onSaveInstanceState(outState: Bundle) {
        editingResult?.let{outState.putString("editingSource",it.source);outState.putString("editingName",it.name)}
        saveCandidate?.let { outState.putString("saveFile",it.absolutePath) }
        saveDraft(); outState.putString("cid", cid); outState.putString("title", title); outState.putString("page", page)
        super.onSaveInstanceState(outState)
    }
    override fun onStart() {
        super.onStart(); active = true
        if (::api.isInitialized && api.access.isNotEmpty()) { if (page == "chat" && cid.isNotEmpty()) loadHistory(); connect() }
    }
    override fun onNewIntent(intent:Intent){
        super.onNewIntent(intent);setIntent(intent)
        intent.getStringExtra("open_conversation")?.takeIf{it.matches(Regex("[A-Za-z0-9_-]{1,64}"))}?.let{target->if(api.access.isNotBlank())selectConversation(target,"Bit-Think")else cid=target}
    }
    override fun onStop() { saveDraft(); active = false; disconnect(); main.removeCallbacksAndMessages(null); streamScheduled = false; super.onStop() }
    override fun onDestroy() { disconnect(); main.removeCallbacksAndMessages(null); io.shutdownNow(); render.shutdownNow(); super.onDestroy() }
}
