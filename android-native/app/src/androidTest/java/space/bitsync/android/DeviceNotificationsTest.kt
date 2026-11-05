package space.bitsync.android

import android.app.Notification
import android.app.NotificationManager
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicReference

/** Explicit device-only acceptance test: a short real user-authorized AI request. */
@RunWith(AndroidJUnit4::class)
class DeviceNotificationsTest {
    private fun waitFor(ms:Long=60000,condition:()->Boolean){val end=System.currentTimeMillis()+ms;while(System.currentTimeMillis()<end){if(condition())return;Thread.sleep(100)};fail("Background result notification was not received")}
    private fun views(v:View):List<View> = listOf(v)+if(v is ViewGroup)(0 until v.childCount).flatMap{views(v.getChildAt(it))}else emptyList()
    @Test fun realReplyNotifiesInBackgroundAndOpensItsConversation(){
        val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
        assertTrue("Notification permission must be enabled for this test",JobNotifications.allowed(context))
        val scenario=ActivityScenario.launch(MainActivity::class.java)
        try {
            val ready=AtomicReference(false)
            waitFor {
                scenario.onActivity { app ->
                    val input=app.findViewById<EditText>(R.id.composer)
                    if(input!=null){input.setText("Android notification test: write 40 concise numbered checks for a mobile chat interface. Plain text only, no tools and no web search.")
                        val send=views(app.window.decorView).firstOrNull{it.contentDescription?.toString()=="Отправить сообщение"};ready.set(send?.isEnabled==true)}
                };ready.get()
            }
            val cid=AtomicReference<String>()
            scenario.onActivity { app ->views(app.window.decorView).first{it.contentDescription?.toString()=="Отправить сообщение"}.performClick() }
            waitFor {
                scenario.onActivity {app ->if(app.findViewById<EditText>(R.id.composer)?.text?.isEmpty()==true&&app.cid.isNotBlank())cid.set(app.cid)}
                !cid.get().isNullOrBlank()
            }
            UiDevice.getInstance(instrumentation).pressHome()
            waitFor(10000){!AppVisibility.visible}
            val manager=context.getSystemService(NotificationManager::class.java)
            val completed=AtomicReference<android.service.notification.StatusBarNotification>()
            waitFor(90000){manager.activeNotifications.firstOrNull{it.id==cid.get().hashCode()&&it.notification.channelId==JobNotifications.COMPLETE}?.let{completed.set(it)};completed.get()!=null}
            val notification=completed.get().notification
            assertEquals("Ответ готов",notification.extras.getString(Notification.EXTRA_TITLE))
            assertEquals(context.packageName,notification.contentIntent.creatorPackage)
            val device=UiDevice.getInstance(instrumentation)
            device.openNotification()
            val card=device.wait(androidx.test.uiautomator.Until.findObject(androidx.test.uiautomator.By.text("Ответ готов")),10000)
            assertNotNull("Result notification must be visible in the notification shade",card)
            card.click()
            // A notification may resume an existing task outside ActivityScenario's tracked
            // instance. Assert the real resumed activity and conversation, not its bookkeeping.
            val opened=AtomicReference<MainActivity>()
            waitFor(10000){
                instrumentation.runOnMainSync {
                    androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry.getInstance()
                        .getActivitiesInStage(androidx.test.runner.lifecycle.Stage.RESUMED)
                        .filterIsInstance<MainActivity>().firstOrNull()?.let{opened.set(it)}
                }
                opened.get()!=null
            }
            instrumentation.runOnMainSync{assertEquals(cid.get(),opened.get().cid)}
            manager.cancel(completed.get().tag,completed.get().id)
        } finally { runCatching{scenario.close()} }
    }
}
