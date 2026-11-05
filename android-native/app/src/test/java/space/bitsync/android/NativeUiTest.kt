package space.bitsync.android

import android.os.Looper
import android.view.View
import android.view.ViewGroup
import androidx.core.graphics.ColorUtils
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputLayout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.android.controller.ActivityController
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit
import java.util.concurrent.ExecutorService

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 35], qualifiers = "w360dp-h800dp")
class NativeUiTest {
    private lateinit var controller: ActivityController<MainActivity>
    private lateinit var activity: MainActivity

    @Before fun start() {
        controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        activity = controller.get()
        val io = activity.javaClass.getDeclaredField("io").apply { isAccessible = true }.get(activity) as ExecutorService
        io.submit {}.get(5, TimeUnit.SECONDS)
        shadowOf(Looper.getMainLooper()).idle()
        call("showLogin", false)
    }
    @After fun stop() { controller.pause().stop().destroy() }

    private fun call(name: String, vararg args: Any) {
        val types = args.map { if (it is Boolean) java.lang.Boolean.TYPE else it.javaClass }.toTypedArray()
        activity.javaClass.declaredMethods.first { it.name.substringBefore('$') == name && it.parameterTypes.contentEquals(types) }.apply { isAccessible = true }.invoke(activity, *args)
    }
    private fun set(name: String, value: Any) { activity.javaClass.getDeclaredField(name).apply { isAccessible = true }.set(activity, value) }
    private fun views(view: View = activity.window.decorView): List<View> = listOf(view) +
        if (view is ViewGroup) (0 until view.childCount).flatMap { views(view.getChildAt(it)) } else emptyList()

    @Test fun emptyLoginShowsFieldErrorsAndKeepsScreen() {
        views().filterIsInstance<MaterialButton>().first { it.text.toString() == "Войти" }.performClick()
        val errors = views().filterIsInstance<TextInputLayout>().mapNotNull { it.error?.toString() }
        assertTrue(errors.contains("Введите почту")); assertTrue(errors.contains("Введите пароль"))
        assertNotNull(activity.findViewById<View>(R.id.email))
    }

    @Test fun streamedAnswerReusesOneRowWithoutChangeAnimations() {
        call("showChat", false)
        set("cid", "test-conversation")
        call("accepted", MainActivity.Pending("request-test", "test-conversation", "Вопрос"))
        repeat(40) {
            call("event", JSONObject().put("type", "chunk").put("payload", JSONObject().put("conversation_id", "test-conversation").put("text", "слово ")))
        }
        shadowOf(Looper.getMainLooper()).idleFor(100, TimeUnit.MILLISECONDS)
        val list = activity.findViewById<RecyclerView>(R.id.message_list)
        assertNull(list.itemAnimator)
        assertEquals(2, list.adapter!!.itemCount)
        val rows = activity.javaClass.getDeclaredField("rows").apply { isAccessible = true }.get(activity) as List<*>
        assertEquals("слово ".repeat(40), (rows.last() as MainActivity.MessageRow).text)
    }

    @Test fun thinkingLivesInReplyAndBecomesOneStreamingAnswer(){
        call("showChat",false);set("cid","test-conversation")
        call("accepted",MainActivity.Pending("test-request","test-conversation","Вопрос"))
        val field=activity.javaClass.getDeclaredField("rows").apply{isAccessible=true}
        val rows=field.get(activity) as List<*>
        assertEquals("status",(rows.last() as MainActivity.MessageRow).role)
        call("event",JSONObject().put("type","status").put("payload",JSONObject().put("text","Проверяю источники")))
        assertEquals(2,rows.size)
        assertEquals("Проверяю источники",(rows.last() as MainActivity.MessageRow).text)
        call("event",JSONObject().put("type","chunk").put("payload",JSONObject().put("text","Готовый ответ")))
        shadowOf(Looper.getMainLooper()).idleFor(100,TimeUnit.MILLISECONDS)
        assertEquals(2,rows.size);assertEquals("assistant",(rows.last() as MainActivity.MessageRow).role)
    }
    @Test fun internalProgressIsNotShownAndUserTextIsNotAHugeBoldHeading(){
        call("showChat",false);set("cid","test-conversation")
        call("accepted",MainActivity.Pending("test-request","test-conversation","Обычный вопрос"))
        call("event",JSONObject().put("type","status").put("payload",JSONObject().put("text","Вызов внутреннего инструмента: служебные подробности")))
        val root=activity.window.decorView
        root.measure(View.MeasureSpec.makeMeasureSpec(1080,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(2200,View.MeasureSpec.EXACTLY))
        root.layout(0,0,root.measuredWidth,root.measuredHeight)
        shadowOf(Looper.getMainLooper()).idle()
        val texts=views().filterIsInstance<android.widget.TextView>()
        assertFalse(texts.any{it.isShown&&it.text.contains("служебные подробности")})
        assertTrue(texts.any{it.isShown&&it.text.toString()=="Готовлю ответ…"})
        val question=texts.first{it.text.toString()=="Обычный вопрос"}
        assertFalse(question.typeface.isBold)
        assertTrue(question.textSize<=16*activity.resources.displayMetrics.scaledDensity)
    }

    @Test fun backgroundStreamDoesNotPullReaderBackToBottom() {
        call("showChat", false); set("cid", "test-conversation")
        call("accepted", MainActivity.Pending("request-test", "test-conversation", "Вопрос"))
        set("followTail", false)
        call("event", JSONObject().put("type", "chunk").put("payload", JSONObject().put("text", "Продолжение")))
        shadowOf(Looper.getMainLooper()).idleFor(100, TimeUnit.MILLISECONDS)
        val following = activity.javaClass.getDeclaredField("followTail").apply { isAccessible = true }.getBoolean(activity)
        assertFalse(following)
    }

    @Test fun primaryTextAndSecondaryTextMeetContrast() {
        val surface = activity.getColor(R.color.surface)
        assertTrue(ColorUtils.calculateContrast(activity.getColor(R.color.on_surface), surface) >= 4.5)
        assertTrue(ColorUtils.calculateContrast(activity.getColor(R.color.on_surface_variant), surface) >= 4.5)
        assertTrue(ColorUtils.calculateContrast(activity.getColor(R.color.on_primary), activity.getColor(R.color.primary)) >= 4.5)
    }

    @Test fun disabledSystemAnimationsLeaveVisibleUsableScreen() {
        val scale = android.animation.ValueAnimator::class.java.getDeclaredMethod("setDurationScale", java.lang.Float.TYPE).apply { isAccessible = true }
        try {
            scale.invoke(null, 0f)
            call("showChat", true)
            shadowOf(Looper.getMainLooper()).idleFor(200, TimeUnit.MILLISECONDS)
            val list = activity.findViewById<RecyclerView>(R.id.message_list)
            assertEquals(View.VISIBLE, list.visibility)
            assertEquals(1f, list.alpha)
            assertNotNull(activity.findViewById<View>(R.id.composer))
        } finally { scale.invoke(null, 1f) }
    }

    @Test fun narrowComposerKeepsActionsBelowTextWithoutOverlapping() {
        val config=android.content.res.Configuration(activity.resources.configuration).apply { fontScale=1.3f }
        @Suppress("DEPRECATION")
        activity.resources.updateConfiguration(config,activity.resources.displayMetrics)
        call("showChat", false)
        activity.modelButton?.text="Очень длинное название режима ответа"
        val root=activity.window.decorView
        val density=activity.resources.displayMetrics.density
        root.measure(View.MeasureSpec.makeMeasureSpec((320*density).toInt(),View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec((640*density).toInt(),View.MeasureSpec.EXACTLY))
        root.layout(0,0,root.measuredWidth,root.measuredHeight)
        val input=activity.findViewById<View>(R.id.composer)
        val mode=activity.modelButton!!
        val inputRect=android.graphics.Rect();val modeRect=android.graphics.Rect()
        assertTrue(input.getGlobalVisibleRect(inputRect));assertTrue(mode.getGlobalVisibleRect(modeRect))
        assertTrue("Mode must be below composer text",modeRect.top>=inputRect.bottom)
        val send=views().filterIsInstance<MaterialButton>().first { it.contentDescription?.toString()=="Отправить сообщение" }
        val sendRect=android.graphics.Rect();send.getGlobalVisibleRect(sendRect)
        assertFalse("Mode must not overlap send",android.graphics.Rect.intersects(modeRect,sendRect))
    }

    @Test @Config(qualifiers = "w320dp-h640dp-night")
    fun largeTextDarkThemeHasScrollableFormAndAccessibleButtons() {
        val config = android.content.res.Configuration(activity.resources.configuration).apply { fontScale = 1.3f }
        @Suppress("DEPRECATION")
        activity.resources.updateConfiguration(config, activity.resources.displayMetrics)
        call("showLogin", false)
        assertTrue(views().any { it is android.widget.ScrollView })
        assertTrue(views().filterIsInstance<MaterialButton>().all { it.minHeight >= (48 * activity.resources.displayMetrics.density).toInt() })
        assertNotNull(activity.findViewById<View>(R.id.password))
        primaryTextAndSecondaryTextMeetContrast()
    }
}
