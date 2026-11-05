package space.bitsync.android

import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[28])
class ResultsTest {
    @Test fun imageMarkdownBecomesNativeImageAndLeavesReadableText(){
        val text="Вот результат.\n![Картинка](/uploads/generated/test/image.png)"
        val result=ResultStore.extract(text,null,"chat-1").single()
        assertEquals(ResultKind.IMAGE,result.kind);assertEquals("chat-1",result.conversation)
        assertEquals("Вот результат.",ResultStore.displayText(text))
    }
    @Test fun htmlAndPdfAreIdentifiedWithoutTreatingEveryWebsiteAsCanvas(){
        assertEquals(ResultKind.HTML,ResultStore.forLink("/uploads/result.html","Холст","chat")!!.kind)
        assertEquals(ResultKind.PDF,ResultStore.forLink("https://example.com/report.pdf","Документ","chat")!!.kind)
        assertNull(ResultStore.forLink("https://example.com/article.html","Статья","chat"))
        assertNull(ResultStore.forLink("javascript:alert(1)","link","chat"))
    }
    @Test fun officeAndNestedAttachmentsRemainAvailableThroughConversationInventory(){
        val attachment=JSONObject("""{"files":[{"name":"deck.pptx"},{"name":"contract.docx"}]}""")
        val refs=ResultStore.extract("",attachment,"chat")
        assertEquals(2,refs.size);assertTrue(refs.all{it.kind==ResultKind.OFFICE&&it.source.startsWith("conversation-file:")})
    }
    @Test fun localPreviewCannotReadSessionOrFilesOutsideItsCache(){
        val context=RuntimeEnvironment.getApplication()
        fun localUri(file:File)=java.net.URI("file","",file.toURI().path,null).toString()
        try{ResultStore.local(context,localUri(File(context.filesDir,"private.txt")));fail("Must reject private files")}catch(_:IllegalArgumentException){}
        val folder=File(context.cacheDir,"previews/test").apply{mkdirs()};val file=File(folder,"test.html").apply{writeText("<h1>Test</h1>")}
        assertEquals(file.canonicalFile,ResultStore.local(context,localUri(file)))
    }
    @Test fun notificationsNeverMatchACompletedTaskFromBeforeSubmission(){
        val watched=WatchedJob("chat",setOf("old"))
        val jobs=JSONArray("""[{"id":"old","conversation_id":"chat","status":"completed"}]""")
        assertNull(watched.find(jobs))
        jobs.put(JSONObject("""{"id":"new","conversation_id":"chat","status":"running"}"""))
        assertEquals("new",watched.find(jobs)!!.getString("id"))
    }
    @Test fun boundNotificationTracksExactGenerationNotAnotherClient(){
        val watched=WatchedJob("chat",emptySet(),id="mine")
        val jobs=JSONArray("""[{"id":"other","conversation_id":"chat","status":"completed"},{"id":"mine","conversation_id":"chat","status":"failed"}]""")
        assertEquals("failed",watched.find(jobs)!!.getString("status"))
        assertEquals("mine",watched.encode().getString("id"))
    }
    @Test fun sandboxHasNoAppOriginOrLocalFileAccessInItsDocument(){
        val html=CanvasDocument.prepare("<html><head><base href=\"https://bit-think.space\"><meta name=\"viewport\" content=\"width=5000\"></head><body><h1>Result</h1></body></html>")
        assertTrue(html.contains("connect-src 'none'"));assertTrue(html.contains("form-action 'none'"));assertTrue(html.contains("frame-src 'none'"))
        assertFalse(html.contains("<base"));assertFalse(html.contains("width=5000"));assertTrue(html.contains("width=device-width"))
        assertEquals("https://appassets.androidplatform.net/result/index.html",CanvasDocument.URL)
    }
    @Test fun slideRuntimeProvidesNativePagingAndWideLayoutIsExplicit(){
        val html=CanvasDocument.prepare("<html><head></head><body><section class='slide'>One</section><section class='slide'>Two</section></body></html>",true)
        assertTrue(html.contains("__btNativeShow"));assertTrue(html.contains("width=1280"))
        assertFalse(CanvasDocument.allowedNavigation("file:///data/private",true));assertFalse(CanvasDocument.allowedNavigation("https://example.com",false));assertTrue(CanvasDocument.allowedNavigation("https://example.com",true))
    }
}
