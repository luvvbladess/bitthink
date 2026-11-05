package space.bitsync.android

import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Handler
import android.os.Looper
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.GravityCompat
import androidx.core.widget.doAfterTextChanged
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.textfield.TextInputEditText
import org.json.JSONArray
import org.json.JSONObject

internal fun MainActivity.fillConversationDrawer() {
    val ticket=++drawerRequest
    drawerPanel.removeAllViews()
    val area=column().apply{setPadding(dp(16),dp(12),dp(16),dp(12))}
    drawerPanel.addView(area,lp(-1,-1))
    val header=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL}
    header.addView(label("Беседы",com.google.android.material.R.style.TextAppearance_Material3_TitleLarge),lp(0,-2).apply{weight=1f;marginStart=dp(8)})
    header.addView(ImageView(this).apply{
        setImageResource(R.drawable.ic_mode_close);imageTintList=ColorStateList.valueOf(color(R.color.on_surface_variant));setPadding(dp(14),dp(14),dp(14),dp(14))
        contentDescription="Закрыть беседы";isFocusable=true;isClickable=true
        setOnClickListener{drawerLayout.closeDrawer(GravityCompat.START)}
    },lp(dp(48),dp(48)))
    area.addView(header)
    area.addView(textButton("Новая беседа") {selectConversation("","Bit-Think")}.apply{
        icon=androidx.core.content.ContextCompat.getDrawable(this@fillConversationDrawer,R.drawable.ic_add)
        gravity=Gravity.START or Gravity.CENTER_VERTICAL
    },lp().apply{topMargin=dp(8);bottomMargin=dp(8)})
    val search=TextInputEditText(this).apply{
        hint="Поиск по беседам";textSize=14f;setSingleLine(true);minHeight=dp(48)
        setPadding(dp(14),dp(10),dp(14),dp(10));setTextColor(color(R.color.on_surface));setHintTextColor(color(R.color.on_surface_variant))
        background=GradientDrawable().apply{setColor(color(R.color.surface_variant));cornerRadius=dp(14).toFloat()}
        importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO
    }
    area.addView(search,lp().apply{bottomMargin=dp(12)})
    val state=body("Загружаем…").apply{textSize=13f;setPadding(dp(8),dp(12),dp(8),dp(12))}
    area.addView(state)
    val list=RecyclerView(this).apply{layoutManager=LinearLayoutManager(this@fillConversationDrawer);itemAnimator=null}
    area.addView(list,lp(-1,0).apply{weight=1f})
    area.addView(textButton("Корзина"){drawerLayout.closeDrawer(GravityCompat.START);showTrash()},lp())
    area.addView(textButton("Профиль и тариф"){drawerLayout.closeDrawer(GravityCompat.START);showProfile()},lp())
    var queryVersion=0
    fun fetch(query:String) {
        val version=++queryVersion
        state.text=if(query.isBlank())"Загружаем беседы…" else "Ищем…";state.visibility=View.VISIBLE
        background {
            try {
                val path=if(query.isBlank())"/conversations?limit=100" else "/conversations/search?q=${android.net.Uri.encode(query)}"
                val data=JSONArray(api.api(path));val entries=(0 until data.length()).map{data.getJSONObject(it)}
                ui {
                    if(ticket!=drawerRequest||version!=queryVersion)return@ui
                    state.text=if(query.isBlank())"Пока нет бесед" else "Ничего не найдено";state.visibility=if(entries.isEmpty())View.VISIBLE else View.GONE
                    list.adapter=DrawerEntriesAdapter(this@fillConversationDrawer,entries)
                }
            } catch(e:Exception) {ui{if(ticket==drawerRequest&&version==queryVersion){state.text="Не удалось загрузить. Откройте панель повторно.";state.visibility=View.VISIBLE}}}
        }
    }
    val debounce=Handler(Looper.getMainLooper());var queued:Runnable?=null
    search.doAfterTextChanged {
        queued?.let{debounce.removeCallbacks(it)}
        val value=it.toString().trim()
        queued=Runnable{if(ticket==drawerRequest&&drawerLayout.isDrawerOpen(GravityCompat.START))fetch(value)}.also{debounce.postDelayed(it,300)}
    }
    fetch("")
}

private class DrawerEntriesAdapter(val app:MainActivity,val entries:List<JSONObject>):RecyclerView.Adapter<DrawerEntriesAdapter.Holder>() {
    class Holder(val text:TextView):RecyclerView.ViewHolder(text)
    override fun getItemCount()=entries.size
    override fun onCreateViewHolder(parent:ViewGroup,viewType:Int):Holder {
        val label=TextView(app).apply{
            textSize=15f;typeface=Typeface.create("sans-serif",Typeface.NORMAL);setTextColor(app.color(R.color.on_surface))
            maxLines=2;ellipsize=TextUtils.TruncateAt.END;gravity=Gravity.CENTER_VERTICAL;minHeight=app.dp(52)
            setPadding(app.dp(12),app.dp(12),app.dp(12),app.dp(12));isClickable=true;isFocusable=true
            layoutParams=RecyclerView.LayoutParams(-1,-2).apply{bottomMargin=app.dp(4)}
        }
        return Holder(label)
    }
    override fun onBindViewHolder(holder:Holder,position:Int) {
        val entry=entries[position];val name=entry.optString("title").ifBlank{"Беседа"};val id=entry.getString("id")
        holder.text.text=name;holder.text.isSelected=id==app.cid
        val fill=if(id==app.cid)androidx.core.graphics.ColorUtils.setAlphaComponent(app.color(R.color.primary),28) else android.graphics.Color.TRANSPARENT
        fun shape(color:Int)=GradientDrawable().apply{setColor(color);cornerRadius=app.dp(12).toFloat()}
        holder.text.background=RippleDrawable(ColorStateList.valueOf(0x2821A0CE),shape(fill),shape(android.graphics.Color.WHITE))
        holder.text.setOnClickListener{app.selectConversation(id,name)}
        holder.text.setOnLongClickListener{app.conversationActions(id,name);true}
    }
}
