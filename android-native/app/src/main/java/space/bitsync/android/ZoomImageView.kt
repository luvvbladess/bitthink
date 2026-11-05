package space.bitsync.android

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.ScaleGestureDetector
import androidx.appcompat.widget.AppCompatImageView

internal class ZoomImageView(context:Context):AppCompatImageView(context) {
    private val transform=Matrix();private var base=1f;private var zoom=1f
    private val scaler=ScaleGestureDetector(context,object:ScaleGestureDetector.SimpleOnScaleGestureListener(){
        override fun onScale(detector:ScaleGestureDetector):Boolean {
            val next=(zoom*detector.scaleFactor).coerceIn(1f,5f)
            transform.postScale(next/zoom,next/zoom,detector.focusX,detector.focusY);zoom=next;constrain();return true
        }
    })
    private val gestures=GestureDetector(context,object:GestureDetector.SimpleOnGestureListener(){
        override fun onDown(e:MotionEvent)=true
        override fun onScroll(e1:MotionEvent?,e2:MotionEvent,dx:Float,dy:Float):Boolean {
            if(zoom>1f){transform.postTranslate(-dx,-dy);constrain()};return true
        }
        override fun onDoubleTap(e:MotionEvent):Boolean {
            if(zoom>1.1f)fit()else{zoom=2.5f;transform.postScale(zoom,zoom,e.x,e.y);constrain()};return true
        }
        override fun onSingleTapConfirmed(e:MotionEvent):Boolean{performClick();return true}
    })
    init{scaleType=ScaleType.MATRIX;contentDescription="Предпросмотр. Увеличение двумя пальцами или двойным нажатием";isFocusable=true}
    fun show(bitmap:Bitmap){setImageBitmap(bitmap);post{fit()}}
    override fun onSizeChanged(w:Int,h:Int,oldw:Int,oldh:Int){super.onSizeChanged(w,h,oldw,oldh);fit()}
    private fun fit(){val d=drawable?:return;if(width<=0||height<=0)return;base=minOf(width.toFloat()/d.intrinsicWidth,height.toFloat()/d.intrinsicHeight);zoom=1f;transform.reset();transform.postScale(base,base);transform.postTranslate((width-d.intrinsicWidth*base)/2,(height-d.intrinsicHeight*base)/2);imageMatrix=transform}
    private fun constrain(){
        val d=drawable?:return;val bounds=android.graphics.RectF(0f,0f,d.intrinsicWidth.toFloat(),d.intrinsicHeight.toFloat());transform.mapRect(bounds)
        val dx=if(bounds.width()<width)(width-bounds.width())/2-bounds.left else if(bounds.left>0)-bounds.left else if(bounds.right<width)width-bounds.right else 0f
        val dy=if(bounds.height()<height)(height-bounds.height())/2-bounds.top else if(bounds.top>0)-bounds.top else if(bounds.bottom<height)height-bounds.bottom else 0f
        transform.postTranslate(dx,dy);imageMatrix=transform
    }
    override fun onTouchEvent(event:MotionEvent):Boolean {scaler.onTouchEvent(event);gestures.onTouchEvent(event);return true}
    override fun performClick():Boolean{super.performClick();return true}
}
