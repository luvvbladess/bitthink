package space.bitsync.android

/** Generated HTML is a result document, never the authenticated app origin. */
internal object CanvasDocument {
    const val ORIGIN="https://appassets.androidplatform.net"
    const val URL="$ORIGIN/result/index.html"
    fun prepare(source:String,wide:Boolean=false):String {
        require(source.length<=16*1024*1024){"Холст слишком большой для просмотра"}
        var html=source.replace(Regex("<meta\\b[^>]*(?:http-equiv\\s*=\\s*['\"]?(?:refresh|content-security-policy)|name\\s*=\\s*['\"]?viewport)[^>]*>",RegexOption.IGNORE_CASE),"")
            .replace(Regex("<base\\b[^>]*>",RegexOption.IGNORE_CASE),"")
        val slide=Regex("class\\s*=\\s*['\"][^'\"]*\\bslide\\b",RegexOption.IGNORE_CASE).containsMatchIn(html)
        if(slide)html=html.replace(Regex("<script\\b[\\s\\S]*?</script>",RegexOption.IGNORE_CASE),"")
        val policy="default-src 'none'; img-src https: data: blob:; style-src 'unsafe-inline' https:; script-src 'unsafe-inline' https:; font-src https: data:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
        val header="<meta http-equiv=\"Content-Security-Policy\" content=\"$policy\"><meta name=\"viewport\" content=\"width=${if(wide)"1280" else "device-width"}, initial-scale=1\">"
        val slideCss=if(slide)"<style>html,body{height:100%;margin:0;overflow:hidden}.slide{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;box-sizing:border-box;visibility:hidden;pointer-events:none}.slide.is-on{visibility:visible;pointer-events:auto}.nav,.counter,[data-deck-ui]{display:none!important}</style>" else ""
        val marker=Regex("<head[^>]*>",RegexOption.IGNORE_CASE)
        val head=marker.find(html)
        html=if(head!=null)html.substring(0,head.range.last+1)+header+slideCss+html.substring(head.range.last+1)else "<head>$header$slideCss</head>"+html
        val runtime="""<script>(()=>{const s=[...document.querySelectorAll('.slide')];if(!s.length)return;let p=0;window.__btNativeShow=(n)=>{p=Math.max(0,Math.min(s.length-1,n));s.forEach((e,i)=>e.classList.toggle('is-on',i===p));return p};window.__btNativeShow(0)})();</script>"""
        return if(slide)html+runtime else html
    }
    fun allowedNavigation(url:String,gesture:Boolean):Boolean = gesture && url.startsWith("https://") && !url.startsWith(ORIGIN)
}
