package space.bitsync.android

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.text.InputType
import android.view.View
import android.widget.ScrollView
import androidx.core.content.FileProvider
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.materialswitch.MaterialSwitch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** Native workspace screens use the same API contracts as the website. */
internal fun MainActivity.featurePage(name: String) {
    hideKeyboard(); screen("workspace", true); toolbar(name, true)
}
internal fun MainActivity.showModels() {
    hideKeyboard()
    background {
        val data = JSONObject(api.api("/models"))
        ui { showModeSheet(data) }
    }
}

internal fun MainActivity.showSearch() {
    featurePage("Поиск по беседам")
    val (box,query)=field("Что найти",View.generateViewId(),InputType.TYPE_CLASS_TEXT)
    content.addView(box,lp().apply{setMargins(dp(24),dp(16),dp(24),dp(8))})
    val scroll=ScrollView(this);val results=column().apply{setPadding(dp(24),dp(16),dp(24),dp(24))}
    val search=filledButton("Найти") {
        val text=query.text.toString().trim()
        if(text.isBlank()) { box.error="Введите запрос";return@filledButton }
        hideKeyboard()
        background {
            val entries=JSONArray(api.api("/conversations/search?q=${Uri.encode(text)}"))
            ui {
                results.removeAllViews()
                if(entries.length()==0)results.addView(body("Ничего не найдено"))
                for(i in 0 until entries.length()){
                    val entry=entries.getJSONObject(i)
                    results.addView(textButton(entry.optString("title","Беседа")){selectConversation(entry.getString("id"),entry.optString("title","Беседа"))})
                    val snippet=entry.optString("snippet").takeIf{it!="null"}.orEmpty()
                    if(snippet.isNotBlank())results.addView(body(snippet))
                }
            }
        }
    }
    content.addView(search,lp().apply{setMargins(dp(24),0,dp(24),0)})
    scroll.addView(results);content.addView(scroll,lp(-1,0).apply{weight=1f})
}

internal fun MainActivity.conversationActions(id: String, name: String) {
    MaterialAlertDialogBuilder(this).setTitle(name).setItems(arrayOf("Переименовать","Удалить в корзину")) { _, action ->
        if(action==0) {
            val (box,edit)=field("Название",View.generateViewId(),InputType.TYPE_CLASS_TEXT)
            edit.setText(name)
            MaterialAlertDialogBuilder(this).setTitle("Название беседы").setView(box)
                .setNegativeButton("Отмена",null).setPositiveButton("Сохранить") { _,_ ->
                    val value=edit.text.toString().trim()
                    if(value.isBlank()) { notice("Введите название"); return@setPositiveButton }
                    background { api.request("/conversations/$id","PATCH",JSONObject().put("title",value)); ui { if(cid==id)title=value;showConversations() } }
                }.show()
        } else MaterialAlertDialogBuilder(this).setTitle("Удалить беседу?").setMessage("Беседу можно будет восстановить из корзины.")
            .setNegativeButton("Отмена",null).setPositiveButton("Удалить") { _,_ ->
                background { api.request("/conversations/$id","DELETE");ui { if(cid==id)selectConversation("","Bit-Think") else showConversations() } }
            }.show()
    }.setNegativeButton("Закрыть",null).show()
}
internal fun MainActivity.showTrash() {
    background {
        val entries=JSONArray(api.api("/conversations/trash"))
        ui {
            featurePage("Корзина")
            if(entries.length()==0)content.addView(body("Корзина пуста"))
            val scroll=ScrollView(this); val container=column().apply{setPadding(dp(24),dp(16),dp(24),dp(24))}
            for(i in 0 until entries.length()) {
                val entry=entries.getJSONObject(i)
                container.addView(body(entry.optString("title")))
                container.addView(textButton("Восстановить") {
                    background { api.api("/conversations/${entry.getString("id")}/restore",JSONObject());ui {showTrash();notice("Беседа восстановлена")} }
                })
            }
            scroll.addView(container);content.addView(scroll,lp(-1,-1))
        }
    }
}

internal fun MainActivity.showProfile() {
    background {
        val profile=JSONObject(api.api("/auth/me"))
        val subscription=JSONObject(api.api("/billing/subscription"))
        ui {
            featurePage("Профиль и тариф")
            val scroll=ScrollView(this); val form=column().apply{setPadding(dp(24),dp(24),dp(24),dp(24))}
            form.addView(body(profile.optString("email")))
            val(box,name)=field("Ваше имя",View.generateViewId(),InputType.TYPE_CLASS_TEXT)
            name.setText(profile.optString("first_name"));form.addView(box,lp().apply{topMargin=dp(20)})
            form.addView(filledButton("Сохранить имя") {
                val value=name.text.toString().trim()
                if(value.isNotBlank())background { api.request("/auth/profile","PATCH",JSONObject().put("first_name",value));ui{notice("Имя сохранено")} }
                else box.error="Введите имя"
            },lp().apply{topMargin=dp(12)})
            val tier=subscription.optString("name").ifBlank{subscription.optString("tier",profile.optString("subscription_tier"))}
            form.addView(body("Ваш тариф: $tier"),lp().apply{topMargin=dp(32)})
            form.addView(textButton("Доступные режимы") {showModels()})
            form.addView(textButton("Память") {showMemory()})
            form.addView(textButton("Личные инструкции") {showInstructions()})
            scroll.addView(form);content.addView(scroll,lp(-1,-1))
        }
    }
}
internal fun MainActivity.showMemory() {
    background {
        val memory=JSONObject(api.api("/memory"))
        ui {
            featurePage("Память")
            val scroll=ScrollView(this);val form=column().apply{setPadding(dp(24),dp(24),dp(24),dp(24))}
            form.addView(body("Сведения и предпочтения, которые помощник учитывает в беседах."))
            val enabled=MaterialSwitch(this).apply{text="Использовать память";isChecked=memory.optBoolean("enabled",true);minHeight=dp(56)}
            form.addView(enabled)
            val(box,notes)=field("Память",View.generateViewId(),InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE)
            notes.setSingleLine(false);notes.minLines=5;notes.maxLines=12;notes.setText(memory.optString("notes"));form.addView(box)
            form.addView(filledButton("Сохранить") {
                val text=notes.text.toString();val on=enabled.isChecked
                background{api.request("/memory","PATCH",JSONObject().put("notes",text).put("enabled",on));ui{notice("Память сохранена")}}
            },lp().apply{topMargin=dp(16)})
            scroll.addView(form);content.addView(scroll,lp(-1,-1))
        }
    }
}
internal fun MainActivity.showInstructions() {
    background {
        val data=JSONObject(api.api("/models/prompts"));val prompts=data.optJSONArray("prompts")?:JSONArray()
        ui {
            featurePage("Личные инструкции")
            val scroll=ScrollView(this);val form=column().apply{setPadding(dp(24),dp(24),dp(24),dp(24))}
            form.addView(body("Выберите инструкцию, которую помощник будет учитывать в ответах."))
            for(i in 0 until prompts.length()) {
                val text=prompts.optString(i)
                form.addView(body(text),lp().apply{topMargin=dp(24)})
                form.addView(textButton(if(!data.isNull("active")&&data.optInt("active")==i)"Активна" else "Использовать") {
                    background {api.api("/models/prompts/$i/activate",JSONObject());ui{showInstructions()}}
                })
                form.addView(textButton("Удалить") {
                    MaterialAlertDialogBuilder(this).setTitle("Удалить инструкцию?").setNegativeButton("Отмена",null).setPositiveButton("Удалить"){_,_->background{api.request("/models/prompts/$i","DELETE");ui{showInstructions()}}}.show()
                })
            }
            val(box,edit)=field("Новая инструкция",View.generateViewId(),InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE)
            edit.setSingleLine(false);edit.minLines=3;edit.maxLines=8
            form.addView(box,lp().apply{topMargin=dp(24)})
            form.addView(filledButton("Добавить") {
                val text=edit.text.toString().trim()
                if(text.isNotBlank())background{api.api("/models/prompts",JSONObject().put("prompt",text));ui{showInstructions()}}
                else box.error="Введите инструкцию"
            })
            scroll.addView(form);content.addView(scroll,lp(-1,-1))
        }
    }
}

internal fun MainActivity.handleUpload(uri: Uri) {
    if(uploadBusy)return
    val previous=cid;uploadBusy=true;updateSend();notice("Загружаем файл…")
    background {
        val temporary=File(cacheDir,"upload-${UUID.randomUUID()}")
        try {
            var name="document"
            contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { if(it.moveToFirst())name=it.getString(0)?:name }
            contentResolver.openInputStream(uri)?.use { input -> temporary.outputStream().use { output ->
                val buffer=ByteArray(32768);var total=0L
                while(true){val n=input.read(buffer);if(n<0)break;total+=n;if(total>32L*1024*1024)error("Можно загрузить файл до 32 МБ");output.write(buffer,0,n)}
            } } ?: error("Не удалось открыть файл")
            val target=if(previous.isEmpty())JSONObject(api.api("/conversations",JSONObject())).getString("id") else previous
            api.upload(temporary,name,contentResolver.getType(uri)?:"application/octet-stream",target)
            ui { if(cid==previous){cid=target;showChat(false)};notice("Файл загружен. Теперь можно задать вопрос.") }
        } finally { temporary.delete();ui {uploadBusy=false;updateSend()} }
    }
}
internal fun MainActivity.showFiles()=showResultsList(false)
internal fun MainActivity.showCanvasResults()=showResultsList(true)
private fun MainActivity.showResultsList(canvasOnly:Boolean) {
    val target=cid
    if(target.isBlank()){notice("Откройте беседу с файлами");return}
    background {
        val files=JSONArray(api.api("/conversations/$target/files"))
        ui {
            featurePage(if(canvasOnly)"Холст результатов" else "Файлы беседы")
            val scroll=ScrollView(this);val form=column().apply{setPadding(dp(24),dp(16),dp(24),dp(24))}
            if(files.length()==0)form.addView(body("В этой беседе пока нет файлов."))
            for(i in 0 until files.length()) {
                val file=files.getJSONObject(i);val name=file.optString("filename",file.optString("name","Файл"));val url=file.optString("download_url")
                val result=NativeResult(url.takeIf{ResultStore.validSource(it)}?:"conversation-file:$target/$name",name,target)
                if(canvasOnly&&result.kind !in listOf(ResultKind.HTML,ResultKind.IMAGE,ResultKind.PDF,ResultKind.OFFICE))continue
                form.addView(body(name),lp().apply{topMargin=dp(20)})
                form.addView(textButton(if(result.kind==ResultKind.HTML)"Открыть холст" else "Открыть") {openResult(result)})
                form.addView(textButton("Скачать или открыть") {if(url.isNotBlank()&&url!="null")downloadResult(url,name) else notice("Файл пока недоступен")})
            }
            scroll.addView(form);content.addView(scroll,lp(-1,-1))
        }
    }
}
internal fun MainActivity.downloadResult(url: String, name: String, data: JSONObject? = null) {
    notice("Получаем файл…")
    background {
        val folder=File(cacheDir,"exports").apply{mkdirs()}
        val clean=File(name).name.replace(Regex("[^\\p{L}\\p{N}._ -]"),"_").take(120).ifBlank{"result"}
        val file=File(folder,"${UUID.randomUUID()}-$clean")
        if(data!=null)api.download(url,file,data)else ResultStore.load(applicationContext,api,NativeResult(url,name,cid)).copyTo(file,overwrite=true)
        ui {
            MaterialAlertDialogBuilder(this).setTitle(clean).setItems(arrayOf("Сохранить в файлы","Открыть","Поделиться")){_, action ->
                if(action==0)chooseSave(file,clean)
                else {
                    val uri=FileProvider.getUriForFile(this,"$packageName.files",file)
                    val mime=android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(clean.substringAfterLast('.',"").lowercase())?:"application/octet-stream"
                    val intent=if(action==1)Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime) else Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM,uri)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    runCatching{startActivity(Intent.createChooser(intent,clean))}.onFailure{notice("Нет приложения для открытия. Сохраните файл.")}
                }
            }.setNegativeButton("Закрыть",null).show()
        }
    }
}
internal fun MainActivity.messageActions(row: MainActivity.MessageRow) {
    val options=if(row.fileUrl?.isNotBlank()==true)arrayOf("Скачать файл","Копировать текст") else if(row.role=="assistant")arrayOf("Копировать","Поделиться текстом","Экспорт в Word","Источники","Ход ответа") else arrayOf("Копировать","Поделиться текстом")
    MaterialAlertDialogBuilder(this).setItems(options){_,index ->
        when(options[index]) {
            "Копировать","Копировать текст" -> {(getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Bit-Think",row.text));notice("Текст скопирован")}
            "Поделиться текстом" -> startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,row.text),"Поделиться"))
            "Экспорт в Word" -> downloadResult("/documents/docx","response.docx",JSONObject().put("markdown",row.text))
            "Скачать файл" -> downloadResult(row.fileUrl!!,row.fileName?:"result")
            "Источники" -> showSources(row.sources?:JSONArray())
            "Ход ответа" -> {
                if(row.steps.isEmpty())notice("Для этого ответа нет сохранённых этапов")
                else MaterialAlertDialogBuilder(this).setTitle("Ход ответа").setMessage(row.steps.joinToString("\n\n")).setPositiveButton("Закрыть",null).show()
            }
        }
    }.show()
}
internal fun MainActivity.showSources(sources: JSONArray = searchSources) {
    if(sources.length()==0){notice("Для этого ответа нет списка источников");return}
    val links=mutableListOf<Pair<String,String>>()
    for(i in 0 until sources.length()) {
        val source=sources.getJSONObject(i)
        if(source.optString("url").startsWith("http"))links.add(source.optString("title",source.optString("url")) to source.getString("url"))
        Regex("\\[([^]]+)\\]\\((https?://[^)\\s]+)\\)").findAll(source.optString("summary")).forEach{links.add(it.groupValues[1] to it.groupValues[2])}
    }
    if(links.isEmpty()){notice("Прямые ссылки смотрите в тексте ответа");return}
    MaterialAlertDialogBuilder(this).setTitle("Источники").setItems(links.map{it.first}.toTypedArray()){_,i ->
        val url=links[i].second;if(url.startsWith("https://")||url.startsWith("http://"))runCatching{startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(url)))}
    }.setNegativeButton("Закрыть",null).show()
}
