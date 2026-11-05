package space.bitsync.android

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.BitmapDrawable
import android.graphics.pdf.PdfDocument
import android.net.Uri
import android.os.Bundle
import android.webkit.WebView
import android.widget.TextView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.atomic.AtomicReference

@RunWith(AndroidJUnit4::class)
class DeviceResultsTest {
    private val instrumentation get()=InstrumentationRegistry.getInstrumentation()
    private val context get()=instrumentation.targetContext
    private fun fixture(name:String)=File(context.cacheDir,"previews/device-qa/$name").apply{parentFile!!.mkdirs()}
    private fun launch(file:File)=ActivityScenario.launch<ResultViewerActivity>(Intent(context,ResultViewerActivity::class.java).putExtra("source",Uri.fromFile(file).toString()).putExtra("name",file.name))
    private fun waitFor(timeout:Long=20000,condition:()->Boolean){val until=System.currentTimeMillis()+timeout;while(System.currentTimeMillis()<until){instrumentation.waitForIdleSync();if(condition())return;Thread.sleep(100)};fail("Device preview did not become ready")}
    private fun imageColor(scenario:ActivityScenario<ResultViewerActivity>):Int? {
        val color=AtomicReference<Int?>()
        scenario.onActivity{activity->val view=activity.findViewById<ZoomImageView>(R.id.result_image);val bitmap=(view.drawable as? BitmapDrawable)?.bitmap;if(bitmap!=null)color.set(bitmap.getPixel(bitmap.width/2,bitmap.height/2))}
        return color.get()
    }
    @Test fun imageOpensInsideAppWithActualBitmap(){
        val file=fixture("BitThink-image-test.png")
        val bitmap=Bitmap.createBitmap(640,480,Bitmap.Config.ARGB_8888);bitmap.eraseColor(Color.rgb(33,160,206))
        file.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)};bitmap.recycle()
        launch(file).use{scenario->waitFor{imageColor(scenario)!=null};assertEquals(Color.rgb(33,160,206),imageColor(scenario))}
    }
    @Test fun pdfRendersTwoDistinctPagesInIsolatedService(){
        val file=fixture("BitThink-pdf-test.pdf")
        val pdf=PdfDocument()
        listOf(Color.rgb(33,160,206),Color.rgb(240,180,40)).forEachIndexed{index,color->
            val page=pdf.startPage(PdfDocument.PageInfo.Builder(400,500,index+1).create());page.canvas.drawColor(color);pdf.finishPage(page)
        }
        file.outputStream().use{pdf.writeTo(it)};pdf.close()
        launch(file).use{scenario->
            waitFor{imageColor(scenario)!=null};assertEquals(Color.rgb(33,160,206),imageColor(scenario))
            scenario.onActivity{it.findViewById<android.view.View>(R.id.result_next).performClick()}
            waitFor{imageColor(scenario)==Color.rgb(240,180,40)}
            scenario.onActivity{assertEquals("2 / 2",it.findViewById<TextView>(R.id.result_page_label).text.toString())}
        }
    }
    @Test fun htmlCanvasKeepsIsolatedOriginAndNativeSlideNavigation(){
        val file=fixture("BitThink-canvas-test.html")
        file.writeText("""<!doctype html><html><head><style>body{background:#0c1012;color:white;font:32px sans-serif}.slide{padding:30px}</style></head><body><section class="slide">One</section><section class="slide">Two</section></body></html>""")
        launch(file).use{scenario->
            val count=AtomicReference<String>()
            waitFor {scenario.onActivity{a->a.findViewById<WebView>(R.id.result_web)?.evaluateJavascript("document.querySelectorAll('.slide').length"){count.set(it)}};count.get()=="2"}
            val counter=AtomicReference<String>()
            waitFor{scenario.onActivity{a->counter.set(a.findViewById<TextView>(R.id.result_page_label).text.toString())};counter.get()=="1 / 2"}
            scenario.onActivity{a->val view=a.findViewById<WebView>(R.id.result_web);assertFalse(view.settings.allowFileAccess);assertFalse(view.settings.allowContentAccess);assertFalse(view.settings.domStorageEnabled);assertEquals(CanvasDocument.URL,view.url);a.findViewById<android.view.View>(R.id.result_next).performClick()}
            val selected=AtomicReference<String>()
            waitFor{scenario.onActivity{a->a.findViewById<WebView>(R.id.result_web).evaluateJavascript("document.querySelector('.slide.is-on').textContent"){selected.set(it)}};selected.get()=="\"Two\""}
        }
    }
}
