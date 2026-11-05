package space.bitsync.android

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.*
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class BitThinkApplication:Application(){
    override fun onCreate(){super.onCreate();registerActivityLifecycleCallbacks(object:ActivityLifecycleCallbacks{
        override fun onActivityStarted(activity:Activity){AppVisibility.started++}
        override fun onActivityStopped(activity:Activity){AppVisibility.started=(AppVisibility.started-1).coerceAtLeast(0)}
        override fun onActivityCreated(a:Activity,b:Bundle?){}
        override fun onActivityResumed(a:Activity){}
        override fun onActivityPaused(a:Activity){}
        override fun onActivitySaveInstanceState(a:Activity,b:Bundle){}
        override fun onActivityDestroyed(a:Activity){}
    })}
}
internal object AppVisibility {@Volatile var started=0;val visible get()=started>0}
internal object JobNotifications {
    const val RUNNING="bitthink-running";const val COMPLETE="bitthink-complete"
    @Volatile var serviceStarted=false
    fun allowed(context:Context)=NotificationManagerCompat.from(context).areNotificationsEnabled()&&(Build.VERSION.SDK_INT<33||ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED)
    fun baseline(api:ApiSession,cid:String):ArrayList<String>{
        val activity=JSONArray(api.api("/chat/activity"))
        return ArrayList((0 until activity.length()).map{activity.getJSONObject(it)}.filter{it.optString("conversation_id")==cid}.map{it.getString("id")})
    }
    fun prepare(context:Context,cid:String,excluded:ArrayList<String>?):Boolean {
        if(excluded==null||!allowed(context))return false
        return runCatching{
            ContextCompat.startForegroundService(context,Intent(context,JobNotificationService::class.java).setAction("watch").putExtra("cid",cid).putStringArrayListExtra("excluded",excluded));serviceStarted=true;true
        }.getOrDefault(false)
    }
    fun bind(context:Context,cid:String,id:String){if(serviceStarted&&id.isNotBlank())runCatching{context.startService(Intent(context,JobNotificationService::class.java).setAction("bind").putExtra("cid",cid).putExtra("job",id))}}
    fun cancel(context:Context,cid:String){if(serviceStarted)runCatching{context.startService(Intent(context,JobNotificationService::class.java).setAction("cancel").putExtra("cid",cid))}}
    fun stop(context:Context){context.stopService(Intent(context,JobNotificationService::class.java));context.getSharedPreferences("job-notifications",0).edit().clear().apply();serviceStarted=false}
    fun openIntent(context:Context,cid:String)=Intent(context,MainActivity::class.java).putExtra("open_conversation",cid).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
}

internal data class WatchedJob(val cid:String,val excluded:Set<String>,val started:Long=System.currentTimeMillis(),var id:String="") {
    fun find(activity:JSONArray):JSONObject?=(0 until activity.length()).map{activity.getJSONObject(it)}.firstOrNull{
        if(id.isNotBlank())it.optString("id")==id else it.optString("conversation_id")==cid&&it.optString("id") !in excluded
    }
    fun encode()=JSONObject().put("cid",cid).put("excluded",JSONArray(excluded.toList())).put("started",started).put("id",id)
}

/** User-started data sync only while a submitted job is outstanding. No always-on polling. */
class JobNotificationService:Service(){
    private val jobs=ConcurrentHashMap<String,WatchedJob>()
    private val main=Handler(Looper.getMainLooper())
    private val worker=Executors.newSingleThreadScheduledExecutor()
    private lateinit var api:ApiSession
    private var foreground=false
    private val prefs get()=getSharedPreferences("job-notifications",0)
    override fun onCreate(){
        super.onCreate();api=ApiSession(applicationContext)
        val manager=getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(JobNotifications.RUNNING,"Выполнение задачи",NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel(JobNotifications.COMPLETE,"Готовые ответы и результаты",NotificationManager.IMPORTANCE_DEFAULT))
        runCatching{val saved=JSONArray(prefs.getString("jobs","[]"));for(i in 0 until saved.length()){val item=saved.getJSONObject(i);val excluded=item.getJSONArray("excluded");val job=WatchedJob(item.getString("cid"),(0 until excluded.length()).map{excluded.getString(it)}.toSet(),item.getLong("started"),item.optString("id"));jobs[job.cid]=job}}
        worker.execute{api.restore()}
        worker.scheduleWithFixedDelay({poll()},800,3000,TimeUnit.MILLISECONDS)
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        when(intent?.action){
            "watch"->{val cid=intent.getStringExtra("cid").orEmpty();if(cid.matches(Regex("[A-Za-z0-9_-]{1,64}")))jobs[cid]=WatchedJob(cid,intent.getStringArrayListExtra("excluded")?.toSet()?:emptySet())}
            "bind"->{val cid=intent.getStringExtra("cid").orEmpty();jobs[cid]?.id=intent.getStringExtra("job").orEmpty()}
            "cancel"->{jobs.remove(intent.getStringExtra("cid").orEmpty())}
        }
        save()
        if(jobs.isEmpty()){stopWatching();return START_NOT_STICKY}
        try{
            ServiceCompat.startForeground(this,901,running(),if(Build.VERSION.SDK_INT>=29)ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0)
            foreground=true;JobNotifications.serviceStarted=true
        }catch(_:Exception){jobs.clear();save();stopSelf();return START_NOT_STICKY}
        return START_STICKY
    }
    private fun running():Notification {
        val cid=jobs.keys.firstOrNull().orEmpty()
        val open=PendingIntent.getActivity(this,901,JobNotifications.openIntent(this,cid),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this,JobNotifications.RUNNING).setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Bit-Think готовит результат").setContentText("Можно свернуть приложение. Сообщим о завершении.")
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true).setSilent(true).setCategory(NotificationCompat.CATEGORY_PROGRESS).build()
    }
    private fun save(){prefs.edit().putString("jobs",JSONArray(jobs.values.map{it.encode()}).toString()).apply()}
    private fun poll(){
        if(jobs.isEmpty())return
        try {
            if(api.access.isBlank()){main.post{jobs.clear();save();stopWatching()};return}
            val activity=JSONArray(api.api("/chat/activity"))
            for(job in jobs.values.toList()){
                val row=job.find(activity)
                if(row!=null){
                    job.id=row.optString("id");val state=row.optString("status")
                    if(state !in listOf("queued","running","external")){
                        if(jobs.remove(job.cid,job))complete(job.cid,when(state){"completed"->"Ответ готов";"cancelled"->"Задача остановлена";else->"Задача завершилась с ошибкой"})
                    }
                }else if(System.currentTimeMillis()-job.started>if(job.id.isBlank())120000L else 6*60*60*1000L){
                    if(jobs.remove(job.cid,job))complete(job.cid,"Откройте беседу, чтобы проверить результат")
                }
            }
            save();main.post{if(jobs.isEmpty())stopWatching()}
        }catch(e:Exception){if(e is ApiException&&e.status in listOf(401,403))main.post{jobs.clear();save();stopWatching()}}
    }
    @Suppress("MissingPermission") private fun complete(cid:String,title:String){
        main.post {
            if(!AppVisibility.visible&&JobNotifications.allowed(this)){
                val open=PendingIntent.getActivity(this,cid.hashCode(),JobNotifications.openIntent(this,cid),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                NotificationManagerCompat.from(this).notify(cid.hashCode(),NotificationCompat.Builder(this,JobNotifications.COMPLETE).setSmallIcon(R.drawable.ic_notification)
                    .setContentTitle(title).setContentText("Нажмите, чтобы открыть беседу в Bit-Think").setContentIntent(open).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build())
            }
        }
    }
    private fun stopWatching(){if(foreground)stopForeground(STOP_FOREGROUND_REMOVE);foreground=false;JobNotifications.serviceStarted=false;stopSelf()}
    override fun onTimeout(startId:Int,fgsType:Int){jobs.keys.forEach{complete(it,"Фоновая проверка приостановлена. Откройте беседу.")};jobs.clear();save();stopWatching()}
    override fun onBind(intent:Intent):IBinder?=null
    override fun onDestroy(){jobs.clear();worker.shutdownNow();api.http.dispatcher.cancelAll();main.removeCallbacksAndMessages(null);JobNotifications.serviceStarted=false;super.onDestroy()}
}
