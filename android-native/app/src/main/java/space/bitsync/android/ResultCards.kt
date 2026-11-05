package space.bitsync.android

import android.content.res.ColorStateList
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

internal fun MainActivity.bindResultCards(container:LinearLayout,results:List<NativeResult>){
    container.removeAllViews();container.visibility=if(results.isEmpty())View.GONE else View.VISIBLE
    for(result in results.distinctBy{it.source}.take(6)){
        val card=column().apply{
            setPadding(dp(12),dp(12),dp(12),dp(12));isClickable=true;isFocusable=true
            val shape=GradientDrawable().apply{setColor(color(R.color.message_paper));cornerRadius=dp(14).toFloat()}
            background=RippleDrawable(ColorStateList.valueOf(0x2021A0CE),shape,null)
            contentDescription=when(result.kind){ResultKind.IMAGE->"Открыть изображение";ResultKind.HTML->"Открыть холст";else->"Открыть ${result.name}"}
            setOnClickListener{openResult(result)}
        }
        if(result.kind==ResultKind.IMAGE){
            val picture=ImageView(this).apply{
                scaleType=ImageView.ScaleType.CENTER_CROP;adjustViewBounds=true;tag=result.source
                background=GradientDrawable().apply{setColor(color(R.color.surface_variant));cornerRadius=dp(10).toFloat()};clipToOutline=true
                contentDescription="Предпросмотр изображения"
            }
            card.addView(picture,lp(-1,dp(180)))
            ResultStore.thumbnail(applicationContext,api,result){bitmap->if(picture.tag==result.source){if(bitmap!=null)picture.setImageBitmap(bitmap)else picture.setImageResource(R.drawable.ic_mode_document)}}
        }
        val title=when(result.kind){ResultKind.IMAGE->"Открыть изображение";ResultKind.HTML->"Открыть холст";else->result.name}
        card.addView(TextView(this).apply{text=title;textSize=14f;setTextColor(color(R.color.on_surface));maxLines=2;ellipsize=android.text.TextUtils.TruncateAt.END;minHeight=dp(36);gravity=Gravity.CENTER_VERTICAL},lp().apply{if(result.kind==ResultKind.IMAGE)topMargin=dp(4)})
        if(result.kind!=ResultKind.IMAGE)card.addView(TextView(this).apply{
            text=when(result.kind){ResultKind.PDF->"PDF · просмотр страниц";ResultKind.HTML->"Сайт, слайды или инфографика";ResultKind.OFFICE->"Просмотр документа";else->"Файл · открыть и сохранить"}
            textSize=12f;setTextColor(color(R.color.on_surface_variant))
        })
        container.addView(card,lp().apply{topMargin=dp(8)})
    }
}
