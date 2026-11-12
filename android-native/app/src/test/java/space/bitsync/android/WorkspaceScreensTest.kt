package space.bitsync.android

import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import com.google.android.material.button.MaterialButton
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.MediaType.Companion.toMediaType
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
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[28])
class WorkspaceScreensTest {
    private lateinit var controller: ActivityController<MainActivity>
    private lateinit var app: MainActivity
    private var responses=mapOf<String,String>()
    private val requests=mutableListOf<Pair<String,String>>()
    @Before fun setup(){
        controller=Robolectric.buildActivity(MainActivity::class.java).setup();app=controller.get();idle()
        val client=OkHttpClient.Builder().addInterceptor { chain ->
            val r=chain.request();synchronized(requests){requests.add(r.method to r.url.encodedPath)}
            Response.Builder().request(r).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body((responses[r.url.encodedPath]?:"{}").toResponseBody("application/json".toMediaType())).build()
        }.build()
        app.api=ApiSession(app.applicationContext,"https://test.invalid/api",client)
    }
    private fun idle(){
        val io=app.javaClass.getDeclaredField("io").apply{isAccessible=true}.get(app) as ExecutorService
        io.submit{}.get(5,TimeUnit.SECONDS);shadowOf(Looper.getMainLooper()).idle()
    }
    private fun views(v:View=app.window.decorView):List<View> = listOf(v)+if(v is ViewGroup)(0 until v.childCount).flatMap{views(v.getChildAt(it))}else emptyList()
    private fun texts()=views().filterIsInstance<TextView>().map{it.text.toString()}
    @After fun teardown(){controller.pause().stop().destroy()}
    @Test fun fileListUsesBackendArrayContract(){
        responses=mapOf("/api/conversations/test/files" to "[{\"name\":\"report.docx\",\"download_url\":\"/conversations/test/files/download?t=test\"}]")
        app.cid="test";app.showFiles();idle()
        assertTrue(texts().contains("report.docx"));assertTrue(texts().contains("Скачать или открыть"))
    }
    @Test fun profileAndTariffAppearAndNameCanBeSaved(){
        responses=mapOf("/api/auth/me" to "{\"email\":\"test@example.invalid\",\"first_name\":\"Имя\"}","/api/billing/subscription" to "{\"name\":\"Pro\"}")
        app.showProfile();idle();assertTrue(texts().contains("test@example.invalid"));assertTrue(texts().contains("Ваш тариф: Pro"))
        views().filterIsInstance<MaterialButton>().first{it.text.toString()=="Сохранить имя"}.performClick();idle()
        assertTrue(requests.contains("PATCH" to "/api/auth/profile"))
    }
    @Test fun memoryRestoresNotesAndSavesUsingPatch(){
        responses=mapOf("/api/memory" to "{\"notes\":\"Краткие ответы\",\"enabled\":true}")
        app.showMemory();idle();assertTrue(texts().contains("Краткие ответы"))
        views().filterIsInstance<MaterialButton>().first{it.text.toString()=="Сохранить"}.performClick();idle()
        assertTrue(requests.contains("PATCH" to "/api/memory"))
    }
    @Test fun instructionsShowServerContentAndActivateCorrectIndex(){
        responses=mapOf("/api/models/prompts" to "{\"prompts\":[\"Объясняй с примерами\"],\"active\":null}")
        app.showInstructions();idle();assertTrue(texts().contains("Объясняй с примерами"))
        views().filterIsInstance<MaterialButton>().first{it.text.toString()=="Использовать"}.performClick();idle()
        assertTrue(requests.contains("POST" to "/api/models/prompts/0/activate"))
    }
    @Test fun trashShowsAndRestoresConversation(){
        responses=mapOf("/api/conversations/trash" to "[{\"id\":\"deleted-id\",\"title\":\"Удалённая беседа\"}]")
        app.showTrash();idle();assertTrue(texts().contains("Удалённая беседа"))
        views().filterIsInstance<MaterialButton>().first{it.text.toString()=="Восстановить"}.performClick();idle()
        assertTrue(requests.contains("POST" to "/api/conversations/deleted-id/restore"))
    }
    @Test fun modeSheetUsesSiteNamesAndGroupsSecondaryModes(){
        val data=org.json.JSONObject("""{"selected":"director","computerAvailable":true,"searchAvailable":true,"researchModel":"gpt-6-sol","astraAvailable":true,"docgenAvailable":true,"models":[{"id":"auto","available":true}]}""")
        app.showModeSheet(data)
        val dialog=org.robolectric.shadows.ShadowDialog.getLatestDialog()
        val all=views(dialog.window!!.decorView).filterIsInstance<TextView>().map{it.text.toString()}
        assertTrue(all.containsAll(listOf("Как отвечать","Экспресс","Оркестратор","Исследование","Ещё режимы")))
        assertFalse(all.contains("Поиск"))
        assertFalse(all.contains("Astra"))
        assertFalse(all.contains("Документы"))
        dialog.dismiss()
    }
    @Test fun drawerOpensOverChatAndPreservesDraftAndList(){
        responses=mapOf("/api/conversations" to "[]")
        app.showChat(false)
        val list=app.findViewById<View>(R.id.message_list)
        val input=app.findViewById<android.widget.EditText>(R.id.composer)
        input.setText("Черновик остаётся в чате")
        app.showConversations(false);idle()
        assertTrue(app.drawerLayout.isDrawerOpen(androidx.core.view.GravityCompat.START))
        assertSame(list,app.findViewById<View>(R.id.message_list))
        assertEquals("Черновик остаётся в чате",input.text.toString())
        app.drawerLayout.closeDrawer(androidx.core.view.GravityCompat.START,false)
        assertSame(list,app.findViewById<View>(R.id.message_list))
    }
}
