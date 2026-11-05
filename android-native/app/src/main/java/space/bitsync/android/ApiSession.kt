package space.bitsync.android

import android.content.Context
import android.security.keystore.*
import android.util.Base64
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrl
import org.json.JSONObject
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import java.io.File
import java.io.IOException
import javax.crypto.*
import javax.crypto.spec.GCMParameterSpec

class ApiException(val status: Int, message: String) : IOException(message)

class ApiSession(private val context: Context, private val base: String = "https://bit-think.space/api",
 val http: OkHttpClient = OkHttpClient.Builder().connectTimeout(20,TimeUnit.SECONDS).readTimeout(120,TimeUnit.SECONDS).pingInterval(10,TimeUnit.SECONDS).build()) {
 companion object { const val WS_URL = "wss://bit-think.space/chat/ws" }
 @Volatile var access=""; private set
 @Volatile private var refresh=""
 private fun getSharedPreferences(name:String,mode:Int)=context.getSharedPreferences(name,mode)
 fun restore()=loadTokens()
 fun login(email:String,password:String){
  val j=JSONObject(api("/auth/login",JSONObject().put("email",email).put("password",password),false))
  access=j.getString("access_token");refresh=j.getString("refresh_token");saveTokens()
 }
 fun logout(){access="";refresh="";getSharedPreferences("session",0).edit().clear().apply();http.dispatcher.cancelAll()}
 private fun saveTokens(){
  val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
  if(!ks.containsAlias("bitsync")){KeyGenerator.getInstance("AES","AndroidKeyStore").apply{init(KeyGenParameterSpec.Builder("bitsync",KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generateKey()}}
  val c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,ks.getKey("bitsync",null))
  val encrypted=c.doFinal(JSONObject().put("a",access).put("r",refresh).toString().toByteArray())
  getSharedPreferences("session",0).edit().putString("data",Base64.encodeToString(c.iv+encrypted,Base64.NO_WRAP)).apply()
 }
 private fun loadTokens(){try{val raw=getSharedPreferences("session",0).getString("data",null)?:return;val bytes=Base64.decode(raw,Base64.NO_WRAP);val ks=KeyStore.getInstance("AndroidKeyStore").apply{load(null)};val c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.DECRYPT_MODE,ks.getKey("bitsync",null),GCMParameterSpec(128,bytes.copyOfRange(0,12)));val j=JSONObject(String(c.doFinal(bytes.copyOfRange(12,bytes.size))));access=j.getString("a");refresh=j.getString("r")}catch(_:Exception){access="";refresh=""}}
 @Synchronized fun api(path:String,body:JSONObject?=null,auth:Boolean=true,retry:Boolean=true):String{
  val b=Request.Builder().url(base+path);if(auth)b.header("Authorization","Bearer $access");if(body!=null)b.post(body.toString().toRequestBody("application/json".toMediaType()))
  http.newCall(b.build()).execute().use{r->val raw=r.body?.string()?:"";if(r.code==401&&auth&&retry&&refresh.isNotEmpty()){renew();return api(path,body,auth,false)};if(!r.isSuccessful){val detail=runCatching{JSONObject(raw).optString("detail")}.getOrDefault("");throw ApiException(r.code,if(r.code==401)"Проверьте почту и пароль или войдите снова" else detail.ifBlank{"Сервер недоступен (${r.code})"})};return raw}
 }
 private fun renew(){val j=JSONObject(api("/auth/refresh",JSONObject().put("refresh_token",refresh),false));access=j.getString("access_token");refresh=j.getString("refresh_token");saveTokens()}

 fun request(path: String, method: String, data: JSONObject? = null): String {
  return execute(path, method, data?.toString()?.toRequestBody("application/json".toMediaType())).use { it.body?.string() ?: "{}" }
 }
 fun upload(file: File, filename: String, mime: String, conversation: String): String {
  val body = MultipartBody.Builder().setType(MultipartBody.FORM)
   .addFormDataPart("conversation_id", conversation)
   .addFormDataPart("file", filename, file.asRequestBody(mime.toMediaType())).build()
  return execute("/documents", "POST", body).use { it.body?.string() ?: "{}" }
 }
 fun download(path: String, target: File, data: JSONObject? = null) {
  execute(path, if(data == null) "GET" else "POST", data?.toString()?.toRequestBody("application/json".toMediaType())).use { response ->
   val body = response.body ?: throw IOException("Сервер вернул пустой файл")
   if(body.contentLength() > 128L * 1024 * 1024) throw IOException("Файл больше 128 МБ")
   body.byteStream().use { input -> target.outputStream().use { output ->
    val buffer=ByteArray(32768); var total=0L
    while(true) { val n=input.read(buffer); if(n<0) break; total+=n; if(total>128L*1024*1024) throw IOException("Файл больше 128 МБ"); output.write(buffer,0,n) }
   } }
  }
 }
 private fun execute(path: String, method: String, body: RequestBody? = null, retry: Boolean = true): Response {
  val url = when {
   path.startsWith("https://") -> path
   path.startsWith("/uploads/") || path.startsWith("/api/") -> base.removeSuffix("/api")+path
   path.startsWith("/") -> base+path
   else -> throw IllegalArgumentException("Небезопасная ссылка")
  }
  val parsed = url.toHttpUrl()
  require(parsed.isHttps) { "Небезопасная ссылка" }
  val origin=base.toHttpUrl()
  val ownHost = parsed.host == origin.host && parsed.port == origin.port && parsed.scheme == origin.scheme
  val builder=Request.Builder().url(url).method(method, body ?: if(method in listOf("POST","PATCH","PUT")) "{}".toRequestBody("application/json".toMediaType()) else null)
  if(ownHost) builder.header("Authorization","Bearer $access")
  val response=http.newCall(builder.build()).execute()
  if(response.code==401 && ownHost && retry && refresh.isNotEmpty()) { response.close(); synchronized(this) { renew() }; return execute(path,method,body,false) }
  if(!response.isSuccessful) { val code=response.code;val raw=response.body?.string().orEmpty();response.close();throw ApiException(code,runCatching{JSONObject(raw).optString("detail")}.getOrDefault("").ifBlank{"Не удалось выполнить запрос ($code)"}) }
  return response
 }

}
