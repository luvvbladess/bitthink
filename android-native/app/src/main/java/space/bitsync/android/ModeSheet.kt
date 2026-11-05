package space.bitsync.android

import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialog
import org.json.JSONObject

internal data class AnswerMode(val id:String,val name:String,val description:String,val icon:Int,val enabled:Boolean)

/** Site's mobile mode drawer, implemented with native Views and branded surfaces. */
internal fun MainActivity.showModeSheet(data: JSONObject) {
    val selected=data.optString("selected","auto")
    val catalog=data.optJSONArray("models")
    fun allowed(id:String):Boolean = catalog?.let { array -> (0 until array.length()).any { array.getJSONObject(it).optString("id")==id && array.getJSONObject(it).optBoolean("available") } }?:false
    val modes=mutableListOf(
        AnswerMode("auto","Экспресс","Быстро и экономно: сам подберёт модель",R.drawable.ic_mode_fast,allowed("auto")),
        AnswerMode("search","Поиск","Свежие ответы с источниками",R.drawable.ic_mode_search,data.optBoolean("searchAvailable")),
        AnswerMode("director","Оркестратор","Задачи с файлами, поиском и инструментами",R.drawable.ic_mode_desktop,data.optBoolean("computerAvailable",allowed("director"))),
        AnswerMode(data.optString("researchModel").takeIf{it.isNotBlank()&&it!="null"}?:"gpt-6-sol","Исследование","Глубокий разбор и проверка источников",R.drawable.ic_mode_research,!data.isNull("researchModel")),
        AnswerMode("gpt-6-astra","Astra","Сложные задачи: код, договоры, файлы",R.drawable.ic_mode_astra,data.optBoolean("astraAvailable")),
        AnswerMode("docgen","Документы","Большой Word-файл или комплект документов",R.drawable.ic_mode_document,data.optBoolean("docgenAvailable"))
    )
    if(modes.none{it.id==selected})modes.add(AnswerMode(selected,data.optString("selectedName","Выбранная модель"),data.optString("selectedDescription"),R.drawable.ic_mode_astra,true))
    val sheet=BottomSheetDialog(this)
    val panel=column().apply { setPadding(dp(16),dp(8),dp(16),dp(20)) }
    fun shape(fill:Int,radius:Int=14,stroke:Int?=null)=GradientDrawable().apply { setColor(fill);cornerRadius=dp(radius).toFloat();if(stroke!=null)setStroke(dp(1),stroke) }
    fun words(value:String,size:Float,secondary:Boolean=false)=TextView(this).apply {
        text=value;textSize=size;setTextColor(color(if(secondary)R.color.on_surface_variant else R.color.on_surface))
        includeFontPadding=true
    }
    val handle=View(this).apply{background=shape(color(R.color.outline),3)}
    panel.addView(FrameLayout(this).apply { addView(handle,FrameLayout.LayoutParams(dp(32),dp(3),Gravity.CENTER)) },lp(-1,dp(16)))
    val header=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL}
    header.addView(words("Как отвечать",14f,true).apply{typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)},lp(0,-2).apply{weight=1f;marginStart=dp(8)})
    val close=ImageView(this).apply {
        setImageResource(R.drawable.ic_mode_close);imageTintList=ColorStateList.valueOf(color(R.color.on_surface_variant));setPadding(dp(14),dp(14),dp(14),dp(14))
        contentDescription="Закрыть выбор режима";isFocusable=true;isClickable=true
        background=RippleDrawable(ColorStateList.valueOf(0x2221A0CE),null,shape(Color.WHITE,24))
        setOnClickListener{sheet.dismiss()}
    }
    header.addView(close,lp(dp(48),dp(48)));panel.addView(header)
    val scroll=ScrollView(this).apply{isFillViewport=false;clipToPadding=false}
    val items=column();scroll.addView(items)
    var expanded=modes.drop(3).any{it.id==selected}
    var saving=false
    fun addMode(mode:AnswerMode) {
        val chosen=mode.id==selected
        val row=LinearLayout(this).apply {
            orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL;minimumHeight=dp(64)
            setPadding(dp(12),dp(10),dp(12),dp(10));isClickable=mode.enabled;isFocusable=true
            contentDescription="${mode.name}. ${mode.description}"+if(!mode.enabled)". Нужен другой тариф" else if(chosen)". Выбран" else ""
            importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_YES
            val fill=if(chosen)0x2021A0CE else if(mode.enabled)0x0AFFFFFF else Color.TRANSPARENT
            val outline=if(chosen)0xFF21A0CE.toInt() else 0x18FFFFFF
            background=RippleDrawable(ColorStateList.valueOf(0x2821A0CE),shape(fill,14,outline),shape(Color.WHITE,14))
        }
        val iconBox=FrameLayout(this).apply{background=shape(if(chosen)0xFF21A0CE.toInt() else 0x14FFFFFF,10)}
        iconBox.addView(ImageView(this).apply{
            setImageResource(mode.icon);imageTintList=ColorStateList.valueOf(if(chosen)0xFF0B1214.toInt() else color(R.color.primary));importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO
        },FrameLayout.LayoutParams(dp(18),dp(18),Gravity.CENTER))
        row.addView(iconBox,lp(dp(32),dp(32)))
        val copy=column()
        copy.addView(words(mode.name,15f).apply{typeface=Typeface.create("sans-serif-medium",Typeface.NORMAL)})
        copy.addView(words(mode.description+if(!mode.enabled)" · Недоступно на тарифе" else "",12f,true).apply{
            maxLines=3;ellipsize=android.text.TextUtils.TruncateAt.END
        },lp().apply{topMargin=dp(2)})
        row.addView(copy,lp(0,-2).apply{weight=1f;marginStart=dp(12);marginEnd=dp(8)})
        if(chosen)row.addView(ImageView(this).apply{
            setImageResource(R.drawable.ic_mode_check);imageTintList=ColorStateList.valueOf(color(R.color.primary));importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO
        },lp(dp(18),dp(18)))
        row.setOnClickListener {
            if(!mode.enabled||saving)return@setOnClickListener
            if(chosen){sheet.dismiss();return@setOnClickListener}
            saving=true;row.alpha=.7f
            background {
                try {
                    api.api("/models/select",JSONObject().put("model",mode.id))
                    ui {selectedModel=mode.id;selectedModelName=mode.name;modelButton?.text=mode.name;sheet.dismiss()}
                } finally {ui{saving=false;row.alpha=1f}}
            }
        }
        items.addView(row,lp().apply{bottomMargin=dp(6)})
    }
    lateinit var rebuild:()->Unit
    rebuild={
        items.removeAllViews();modes.take(3).forEach{addMode(it)}
        items.addView(words("Выбор применяется к следующим сообщениям. Текущий ответ продолжит работу.",12f,true),lp().apply{setMargins(dp(8),dp(8),dp(8),dp(12))})
        val more=words(if(expanded)"Скрыть дополнительные режимы" else "Ещё режимы",14f).apply {
            gravity=Gravity.CENTER_VERTICAL;minHeight=dp(48);setPadding(dp(8),0,dp(8),0);isClickable=true;isFocusable=true
            setOnClickListener{expanded=!expanded;rebuild()}
        }
        items.addView(more)
        if(expanded)modes.drop(3).forEach{addMode(it)}
    }
    rebuild();panel.addView(scroll,lp())
    sheet.setContentView(panel)
    sheet.setOnShowListener {
        val bottom=sheet.findViewById<FrameLayout>(com.google.android.material.R.id.design_bottom_sheet)!!
        bottom.background=shape(color(R.color.surface_variant),22)
        val height=(resources.displayMetrics.heightPixels*.86f).toInt()
        sheet.behavior.maxHeight=height;sheet.behavior.state=BottomSheetBehavior.STATE_EXPANDED;sheet.behavior.skipCollapsed=true
        ViewCompat.setOnApplyWindowInsetsListener(panel){_,insets->
            val bar=insets.getInsets(WindowInsetsCompat.Type.systemBars());panel.setPadding(dp(16),dp(8),dp(16),dp(16)+bar.bottom);insets
        }
        ViewCompat.requestApplyInsets(panel)
    }
    sheet.show()
}
