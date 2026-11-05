package space.bitsync.android

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.Base64
import android.util.LruCache
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.Executors

internal enum class ResultKind { IMAGE, PDF, HTML, OFFICE, FILE }
internal data class NativeResult(val source:String,val name:String,val conversation:String="") {
    val kind:ResultKind get() {
        val extension=(name.substringAfterLast('.',"").takeIf{it.isNotBlank()}?:Uri.parse(source).lastPathSegment.orEmpty().substringAfterLast('.',"")).lowercase()
        return when(extension){"png","jpg","jpeg","webp","gif","bmp","heic","avif"->ResultKind.IMAGE;"pdf"->ResultKind.PDF;"html","htm"->ResultKind.HTML;"doc","docx","odt","rtf","xls","xlsx","ods","ppt","pptx","odp"->ResultKind.OFFICE;else->ResultKind.FILE}
    }
}

internal object ResultStore {
    val workers=Executors.newFixedThreadPool(2)
    val main=android.os.Handler(android.os.Looper.getMainLooper())
    private val images=object:LruCache<String,Bitmap>(12*1024*1024){override fun sizeOf(key:String,value:Bitmap)=value.allocationByteCount}
    private val imagePattern=Regex("!\\[([^]]*)]\\(([^)\\s]+)\\)")
    private val filePattern=Regex("(?<!!)\\[([^]]+)]\\(([^)\\s]+)\\)")
    fun forLink(source:String,label:String,conversation:String):NativeResult? {
        if(!validSource(source))return null
        val name=label.takeIf{it.contains('.')&&!it.contains('/')}?:Uri.parse(source).lastPathSegment.orEmpty()
        val result=NativeResult(source,name,conversation)
        return result.takeIf{it.kind!=ResultKind.FILE&&(it.kind!=ResultKind.HTML||source.startsWith("/uploads/")||source.startsWith("https://bit-think.space/"))}
    }
    fun digest(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString(""){"%02x".format(it)}
    private fun scope(api:ApiSession):String {
        val user=runCatching{JSONObject(String(Base64.decode(api.access.split('.')[1],Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING))).optString("sub")}.getOrDefault("session")
        return digest(user).take(20)
    }
    fun validSource(value:String)=value.startsWith("https://")||value.startsWith("/uploads/")||value.startsWith("/conversations/")||value.startsWith("/api/")||value.startsWith("file://")||value.startsWith("conversation-file:")
    fun extract(text:String,attachment:JSONObject?,conversation:String):List<NativeResult> {
        val results=mutableListOf<NativeResult>()
        imagePattern.findAll(text).forEach { match ->
            val source=match.groupValues[2]
            if(validSource(source))results.add(NativeResult(source,Uri.parse(source).lastPathSegment?.takeIf{it.contains('.')}?:"image.png",conversation))
        }
        filePattern.findAll(text).forEach{match->forLink(match.groupValues[2],match.groupValues[1],conversation)?.let{results.add(it)}}
        fun add(item:JSONObject?) {
            if(item==null)return
            val source=item.optString("original_url").takeIf{it.isNotBlank()&&it!="null"}?:item.optString("url")
            val name=item.optString("name",item.optString("filename","Результат"))
            if(validSource(source))results.add(NativeResult(source,name,conversation))
            else if(name!="Результат"&&conversation.isNotBlank())results.add(NativeResult("conversation-file:$conversation/$name",name,conversation))
            item.optJSONArray("files")?.let{array->for(i in 0 until array.length())add(array.optJSONObject(i))}
        }
        add(attachment)
        return results.distinctBy{it.source}
    }
    fun displayText(text:String)=imagePattern.replace(text){if(validSource(it.groupValues[2]))"" else it.value}.trim()
    fun local(context:Context,source:String):File {
        require(source.startsWith("file://")){"Неверный локальный результат"}
        val uri=java.net.URI(source)
        require(uri.authority.isNullOrEmpty()){ "Недоступный локальный результат" }
        val file=File(uri).canonicalFile
        val previews=File(context.cacheDir,"previews").canonicalFile
        val exports=File(context.cacheDir,"exports").canonicalFile
        require(file.path.startsWith(previews.path+File.separator)||file.path.startsWith(exports.path+File.separator)){"Результат недоступен"}
        require(file.isFile){"Локальный файл больше недоступен"};return file
    }
    fun load(context:Context,api:ApiSession,result:NativeResult):File {
        if(result.source.startsWith("file://"))return local(context,result.source)
        require(validSource(result.source)){"Небезопасная ссылка"}
        var source=result.source
        if(source.startsWith("conversation-file:")){
            require(result.conversation.matches(Regex("[A-Za-z0-9_-]{1,64}"))){"Недоступная беседа"}
            val files=org.json.JSONArray(api.api("/conversations/${result.conversation}/files"))
            val metadata=(0 until files.length()).map{files.getJSONObject(it)}.firstOrNull{it.optString("name")==result.name}?:error("Файл больше недоступен")
            source=metadata.optString("download_url").takeIf{validSource(it)}?:error("Файл пока недоступен")
            source+="&native_version=${metadata.optInt("version",1)}"
        }
        val folder=File(context.cacheDir,"previews/${scope(api)}").apply{mkdirs()}
        val extension=result.name.substringAfterLast('.',"bin").filter{it.isLetterOrDigit()}.take(8).ifBlank{"bin"}
        val target=File(folder,digest(source)+"."+extension)
        synchronized(this) {
            if(target.isFile&&target.length()>0)return target
            val temporary=File(folder,"${UUID.randomUUID()}.part")
            try {api.download(source,temporary);require(temporary.length()>0){"Получен пустой файл"};check(temporary.renameTo(target)){"Не удалось сохранить предпросмотр"};return target}
            finally{temporary.delete()}
        }
    }
    fun fromBase64(context:Context,encoded:String,name:String):String {
        require(encoded.length<=64*1024*1024){"Файл слишком большой для встроенного просмотра"}
        val folder=File(context.cacheDir,"previews/received").apply{mkdirs()}
        val suffix=name.substringAfterLast('.',"bin").filter{it.isLetterOrDigit()}.take(8)
        val file=File(folder,"${UUID.randomUUID()}.$suffix")
        file.writeBytes(Base64.decode(encoded,Base64.DEFAULT))
        return Uri.fromFile(file).toString()
    }
    fun bitmap(file:File,maxSide:Int=2048):Bitmap {
        val bounds=BitmapFactory.Options().apply{inJustDecodeBounds=true};BitmapFactory.decodeFile(file.path,bounds)
        require(bounds.outWidth>0&&bounds.outHeight>0){"Изображение не удалось прочитать"}
        var sample=1;while(maxOf(bounds.outWidth,bounds.outHeight)/sample>maxSide)sample*=2
        return BitmapFactory.decodeFile(file.path,BitmapFactory.Options().apply{inSampleSize=sample})?:error("Изображение не удалось открыть")
    }
    fun thumbnail(context:Context,api:ApiSession,result:NativeResult,callback:(Bitmap?)->Unit) {
        val key=scope(api)+":"+result.source
        images.get(key)?.let{callback(it);return}
        workers.execute{
            val bitmap=runCatching{bitmap(load(context.applicationContext,api,result),640)}.getOrNull()
            if(bitmap!=null)images.put(key,bitmap)
            main.post{callback(bitmap)}
        }
    }
    fun clear(context:Context){images.evictAll();File(context.cacheDir,"previews").deleteRecursively()}
}
