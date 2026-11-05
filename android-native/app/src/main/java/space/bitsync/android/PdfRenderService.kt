package space.bitsync.android

import android.app.Service
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.pdf.PdfRenderer
import android.os.*
import java.util.concurrent.Executors

/** Receives only a read-only FD; runs in an isolated UID without account or network access. */
class PdfRenderService:Service() {
    private val worker=Executors.newSingleThreadExecutor()
    private var document:PdfRenderer?=null
    private val inbox=Messenger(object:Handler(Looper.getMainLooper()){
        override fun handleMessage(message:Message){
            val target=message.replyTo?:return
            val operation=message.what;val page=message.arg1;val request=message.arg2
            @Suppress("DEPRECATION") val fd=message.data.getParcelable<ParcelFileDescriptor>("file")
            worker.execute{
                try {
                    if(operation==1){document?.close();document=PdfRenderer(requireNotNull(fd));target.send(Message.obtain(null,1,document!!.pageCount,0))}
                    else if(operation==2){
                        val pdf=document?:error("Документ не открыт")
                        pdf.openPage(page.coerceIn(0,pdf.pageCount-1)).use { sheet ->
                            val scale=minOf(2048f/sheet.width,2048f/sheet.height)
                            val image=Bitmap.createBitmap((sheet.width*scale).toInt().coerceAtLeast(1),(sheet.height*scale).toInt().coerceAtLeast(1),Bitmap.Config.ARGB_8888)
                            image.eraseColor(Color.WHITE);sheet.render(image,null,null,PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                            val shared=if(Build.VERSION.SDK_INT>=31)image.asShared()else image.copy(Bitmap.Config.ARGB_8888,false)
                            target.send(Message.obtain(null,2,page,request).apply{data=Bundle().apply{putParcelable("bitmap",shared)}})
                            if(shared!==image)image.recycle()
                        }
                    }
                } catch(e:Exception){runCatching{target.send(Message.obtain(null,3,request,0).apply{data=Bundle().apply{putString("error",if(operation==1)"Не удалось открыть PDF. Возможно, он защищён паролем или повреждён." else "Не удалось отобразить страницу")}})}}
            }
        }
    })
    override fun onBind(intent:Intent)=inbox.binder
    override fun onDestroy(){worker.execute{document?.close();document=null};worker.shutdown();super.onDestroy()}
}
