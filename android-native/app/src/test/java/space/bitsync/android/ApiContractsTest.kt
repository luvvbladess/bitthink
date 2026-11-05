package space.bitsync.android

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[28])
class ApiContractsTest {
    private lateinit var server: MockWebServer
    private lateinit var session: ApiSession
    private lateinit var client: OkHttpClient
    @Before fun setup() {
        val certificate=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").addSubjectAlternativeName("127.0.0.1").build()
        val serverTls=HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls=HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        server=MockWebServer();server.useHttps(serverTls.sslSocketFactory(),false);server.start()
        client=OkHttpClient.Builder().sslSocketFactory(clientTls.sslSocketFactory(),clientTls.trustManager).build()
        session=ApiSession(RuntimeEnvironment.getApplication(),server.url("/api").toString(),client)
        session.javaClass.getDeclaredField("access").apply{isAccessible=true}.set(session,"test-only-token")
    }
    @After fun stop(){server.shutdown()}
    @Test fun renameUsesPatchAndJsonNotPost() {
        server.enqueue(MockResponse().setBody("{\"ok\":true}"))
        session.request("/conversations/test","PATCH",JSONObject().put("title","Название"))
        val request=server.takeRequest(2,TimeUnit.SECONDS)!!
        assertEquals("PATCH",request.method);assertEquals("/api/conversations/test",request.path)
        assertEquals("Название",JSONObject(request.body.readUtf8()).getString("title"))
        assertEquals("Bearer test-only-token",request.getHeader("Authorization"))
    }
    @Test fun deletionAndMemoryUseTheirActualHttpMethods() {
        server.enqueue(MockResponse().setBody("{}"));session.request("/conversations/test","DELETE")
        assertEquals("DELETE",server.takeRequest().method)
        server.enqueue(MockResponse().setBody("{}"));session.request("/memory","PATCH",JSONObject().put("notes","Память").put("enabled",true))
        val request=server.takeRequest();assertEquals("PATCH",request.method);assertTrue(JSONObject(request.body.readUtf8()).getBoolean("enabled"))
    }
    @Test fun uploadUsesMultipartFieldNamesExpectedByBackend() {
        server.enqueue(MockResponse().setBody("{\"ok\":true}"))
        val file=File.createTempFile("bitsync-upload",".txt");file.writeText("test")
        try{session.upload(file,"test.txt","text/plain","conversation-1")}finally{file.delete()}
        val request=server.takeRequest();val body=request.body.readUtf8()
        assertEquals("/api/documents",request.path);assertTrue(request.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        assertTrue(body.contains("name=\"conversation_id\""));assertTrue(body.contains("conversation-1"));assertTrue(body.contains("name=\"file\""))
    }
    @Test fun exportPostsMarkdownAndSavesActualResponseBytes() {
        server.enqueue(MockResponse().setBody("binary-test-document"))
        val file=File.createTempFile("bitsync-export",".docx")
        try {
            session.download("/documents/docx",file,JSONObject().put("markdown","# Ответ"))
            assertEquals("binary-test-document",file.readText())
            val request=server.takeRequest();assertEquals("POST",request.method)
            assertEquals("# Ответ",JSONObject(request.body.readUtf8()).getString("markdown"))
        }finally{file.delete()}
    }
    @Test fun apiFailuresRemainFailures() {
        server.enqueue(MockResponse().setResponseCode(403).setBody("{\"detail\":\"Нет доступа\"}"))
        try{session.request("/conversations/test","DELETE");fail("Must not report success")}catch(e:ApiException){assertEquals(403,e.status);assertEquals("Нет доступа",e.message)}
    }
    @Test fun externalFileOriginNeverReceivesAccountToken() {
        val external=MockWebServer()
        // An insecure external URL must be rejected before any request or token is sent.
        external.start()
        val target=File.createTempFile("bitsync-denied",".bin")
        try{session.download(external.url("/file").toString(),target);fail("HTTP file must be rejected")}catch(_:IllegalArgumentException){}finally{target.delete();external.shutdown()}
    }
}
