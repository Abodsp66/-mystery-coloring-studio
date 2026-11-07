"""Real independent JS worker + vector output checks, with off-site requests blocked."""
import argparse,asyncio,base64,hashlib,json,math,os,time
from pathlib import Path
from urllib.parse import urlparse
import fitz
from playwright.async_api import async_playwright,expect

async def download(page,selector,directory):
    directory.mkdir(parents=True,exist_ok=True)
    async with page.expect_download() as event:await page.locator(selector).click()
    item=await event.value;assert await item.failure() is None
    path=directory/item.suggested_filename;await item.save_as(path);return path

async def convert(page):
    started=time.monotonic();await page.locator('#process').click()
    await expect(page.locator('#cancel')).to_be_hidden(timeout=45000)
    await expect(page.locator('#pdf')).to_be_enabled()
    assert await page.locator('#missing').inner_text()=='0'
    return round((time.monotonic()-started)*1000,1)

async def make_image(page,mime='image/png',tiles=False):
    encoded=await page.evaluate('''({mime,tiles})=>{
        const c=document.createElement('canvas');c.width=320;c.height=320;const x=c.getContext('2d');
        if(tiles){for(let y=0;y<4;y++)for(let i=0;i<8;i++){
            x.fillStyle=`rgb(${20+i*30},${25+y*55},120)`;x.fillRect(i*40,y*80,40,80);
        }}else{x.fillStyle='#e8d7b7';x.fillRect(0,0,320,320);x.fillStyle='#518492';x.fillRect(40,40,240,240);x.fillStyle='#be7660';x.fillRect(100,100,120,120);}
        return c.toDataURL(mime,.94).split(',')[1];}''',{'mime':mime,'tiles':tiles})
    return {'name':'original.'+{'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[mime],
        'mimeType':mime,'buffer':base64.b64decode(encoded)}

async def vector_audit(page):
    return await page.evaluate('''async()=>{
        const r=window.__flowResult,c=document.createElement('canvas'),ctx=c.getContext('2d');
        const bad=[];let checked=0;
        for(const cell of r.cells){const p=cell.label,g=r.glyphs[p.code],em=p.pt*25.4/72/r.mm;
            const gap=(r.settings.stroke/2+.15)/r.mm,hw=em*g.width/2+gap,hh=em*g.height/2+gap;
            const angle=p.angle*Math.PI/180,path=new Path2D(cell.path);
            for(let y=0;y<=6;y++)for(let x=0;x<=6;x++){
                const dx=-hw+2*hw*x/6,dy=-hh+2*hh*y/6;
                const px=p.x+dx*Math.cos(angle)-dy*Math.sin(angle),py=p.y+dx*Math.sin(angle)+dy*Math.cos(angle);
                if(!ctx.isPointInPath(path,px,py,'evenodd'))bad.push(cell.id);checked++;
            }
        }
        const paths=r.palette.map((_,i)=>r.cells.filter(c=>c.color===i).map(c=>c.path).join(''));
        const svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${r.w}" height="${r.h}" viewBox="0 0 ${r.w} ${r.h}">${paths.map((d,i)=>`<path d="${d}" fill="rgb(${r.palette[i]})" fill-rule="evenodd"/>`).join('')}</svg>`;
        c.width=r.w;c.height=r.h;const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'})),im=new Image();im.src=url;await im.decode();ctx.drawImage(im,0,0);URL.revokeObjectURL(url);
        const pixels=ctx.getImageData(0,0,r.w,r.h).data,colors=new Uint8Array(r.cells.length+1);
        for(const cell of r.cells)colors[cell.id]=cell.color;
        const at=i=>colors[r.regionMap[i]];let samples=0,mismatch=0,transparent=0;
        for(let y=4;y<r.h-4;y+=3)for(let x=4;x<r.w-4;x+=3){const i=y*r.w+x,color=at(i);
            if([-3,0,3].some(dy=>[-3,0,3].some(dx=>at(i+dy*r.w+dx)!==color)))continue;
            const target=r.palette[color],error=Math.max(...target.map((v,k)=>Math.abs(v-pixels[i*4+k])));
            samples++;if(error>4)mismatch++;if(pixels[i*4+3]<254)transparent++;
        }
        return {inkSamples:checked,invalidCells:[...new Set(bad)],interiorSamples:samples,colorMismatches:mismatch,transparentInterior:transparent};
    }''')

async def main(args):
    args.output.mkdir(parents=True,exist_ok=True);summary={};errors=[];failed=[];remote=[];requests=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',proxy={'server':os.environ['HTTPS_PROXY'],'bypass':'127.0.0.1,localhost'})
        context=await browser.new_context(viewport={'width':1440,'height':1050})
        async def local_only(route):
            host=urlparse(route.request.url).hostname
            if host and host not in ('127.0.0.1','localhost'):remote.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',local_only)
        await context.add_init_script('''const RealWorker=window.Worker;window.Worker=class extends RealWorker{
            constructor(...a){super(...a);this.addEventListener('message',e=>{if(e.data.type==='result')window.__flowResult=e.data.result;});}};''')
        page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('requestfailed',lambda r:failed.append(r.url));page.on('request',lambda r:requests.append(r.url))
        await page.goto(args.url);await expect(page.locator('html')).to_have_attribute('dir','rtl')
        await page.locator('#file').set_input_files({'name':'broken.png','mimeType':'image/png','buffer':b'broken'})
        await expect(page.locator('#status')).to_contain_text('تعذر فتح الصورة');await expect(page.locator('#process')).to_be_disabled()
        summary['invalid_upload']='passed'
        await page.locator('#demo').click();await expect(page.locator('#process')).to_be_enabled()
        summary['demoWallMS']=await convert(page)
        report=json.loads((await download(page,'#report',args.output)).read_text());summary['demo']=report['metrics']
        assert 'independent JavaScript' in report['engine'];assert report['metrics']['missing']==0
        assert report['metrics']['detailChangedPct']<=2.5;assert report['metrics']['totalMS']<15000
        audit=await vector_audit(page);summary['independentVectorAudit']=audit
        assert not audit['invalidCells'],audit
        assert audit['colorMismatches']/audit['interiorSamples']<.002,audit
        assert audit['transparentInterior']==0,audit
        await page.screenshot(path=str(args.output/'portrait-outline.png'),full_page=True)
        svg=await download(page,'#svg',args.output);assert 'data:font/ttf;base64,' in svg.read_text()
        pdf=await download(page,'#pdf',args.output)
        origins=await page.evaluate('''()=>{const r=window.__flowResult;return r.cells.map(c=>{
            const p=c.label,g=r.glyphs[p.code],em=p.pt*25.4/72,a=p.angle*Math.PI/180;
            return {code:p.code,x:r.offset[0]+p.x*r.mm-em*g.cx*Math.cos(a)+em*g.cy*Math.sin(a),
                y:r.offset[1]+p.y*r.mm-em*g.cx*Math.sin(a)-em*g.cy*Math.cos(a),angle:a};});}''')
        with fitz.open(pdf) as d:
            dims=[d[0].rect.width*25.4/72,d[0].rect.height*25.4/72]
            assert abs(dims[0]-210)<.01 and abs(dims[1]-297)<.01,dims
            assert not d[0].get_images();assert any('FlowSymbols' in f[3] for f in d[0].get_fonts())
            assert 'ALL REGIONS CODED' in d[0].get_text()
            spans=[]
            for block in d[0].get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    for span in line['spans']:
                        if 'FlowSymbols' in span['font']:spans.append((span,line['dir']))
            for origin in origins:
                candidates=[(span,direction) for span,direction in spans if span['text']==origin['code']]
                error,span,direction=min((math.hypot(span['origin'][0]*25.4/72-origin['x'],span['origin'][1]*25.4/72-origin['y']),span,direction) for span,direction in candidates)
                assert error<.02,(origin,error)
                assert abs(direction[0]-math.cos(origin['angle']))<1e-5 and abs(direction[1]-math.sin(origin['angle']))<1e-5,(origin,direction)
        summary['vector_A4_PDF_and_SVG_embedded_font']='passed'
        summary['PDF_label_origins_and_rotation']='passed'
        for view in ['solution','compare','overlay','source','outline']:
            await page.locator(f'[data-view="{view}"]').click()
            if view=='overlay':await page.locator('#opacity').fill('30');await expect(page.locator('.overlay .solution')).to_have_css('opacity','0.3')
        summary['views_and_overlay']='passed'
        # Benchmark two further ORIGINAL illustrations at the same UI settings.
        benchmark=[{'fixture':'reader portrait (demo.svg)','metrics':report['metrics']}]
        root=Path(__file__).resolve().parents[1]
        for fixture in ['original-attic','original-courtyard']:
            source=(root/'tests/flow-fixtures'/(fixture+'.svg')).read_bytes()
            data=await page.evaluate('''async base64=>{const image=new Image();image.src='data:image/svg+xml;base64,'+base64;await image.decode();
                const c=document.createElement('canvas');c.width=image.naturalWidth;c.height=image.naturalHeight;c.getContext('2d').drawImage(image,0,0);
                return c.toDataURL('image/png').split(',')[1];}''',base64.b64encode(source).decode())
            await page.locator('#file').set_input_files({'name':fixture+'.png','mimeType':'image/png','buffer':base64.b64decode(data)})
            await convert(page)
            measured=json.loads((await download(page,'#report',args.output/fixture)).read_text())
            independent=await vector_audit(page);assert not independent['invalidCells'],independent
            assert independent['colorMismatches']/independent['interiorSamples']<.002,independent
            benchmark.append({'fixture':fixture,'sourceSHA256':hashlib.sha256(source).hexdigest(),'metrics':measured['metrics'],'vectorAudit':independent})
        benchmark_report={'method':'Chromium, actual Worker, no offsite requests; original CC0 fixtures, same A4/18 colors/5pt/.16mm/.7 density/2.5% budget settings',
            'sourceSHA256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'flow-studio').glob('*.mjs')},'fixtures':benchmark}
        (args.output/'benchmark.json').write_text(json.dumps(benchmark_report,ensure_ascii=False,indent=2)+'\n')
        summary['three_original_fixtures']='passed'
        await page.locator('#demo').click();await convert(page)
        # Recode a large real cell; topology must remain unchanged and undo exact.
        cell_id=await page.evaluate('window.__flowResult.cells.slice().sort((a,b)=>b.area-a.area)[0].id')
        old=await page.locator('#art [data-region]').evaluate_all('n=>n.map(p=>p.getAttribute("d"))')
        await page.locator(f'[data-region="{cell_id}"]').dispatch_event('click');initial=await page.locator('#code').input_value()
        await page.locator('#code').select_option(index=(int(initial)+1)%len(report['palette']))
        await page.locator('#recode').click();await expect(page.locator('#undo')).to_be_enabled()
        assert old==await page.locator('#art [data-region]').evaluate_all('n=>n.map(p=>p.getAttribute("d"))')
        await page.locator('#undo').click();await expect(page.locator('#undo')).to_be_disabled()
        summary['manual_code_and_undo']='passed'
        previous=await page.evaluate('window.__flowResult.network')
        await page.locator('#variant').click();await expect(page.locator('#cancel')).to_be_hidden(timeout=45000)
        await expect(page.locator('#pdf')).to_be_enabled();assert previous!=await page.evaluate('window.__flowResult.network')
        summary['flow_variant']='passed'
        for mime in ['image/png','image/jpeg','image/webp']:
            await page.locator('#file').set_input_files(await make_image(page,mime))
            await expect(page.locator('#process')).to_be_enabled();await convert(page)
            assert (await vector_audit(page))['invalidCells']==[]
            summary[mime]='passed'
        if not await page.locator('#catalog').is_visible():await page.locator('details').first.locator('summary').click()
        palette=['#%02x%02x78'%(20+x*30,25+y*55) for y in range(4) for x in range(8)]
        await page.locator('#file').set_input_files(await make_image(page,tiles=True))
        await page.locator('#catalog').set_input_files({'name':'pencils.json','mimeType':'application/json','buffer':json.dumps({'name':'original 32 colors','colors':palette}).encode()})
        await expect(page.locator('#colors')).to_be_disabled();await page.locator('#density').select_option('0')
        await page.locator('#scan').uncheck();await page.locator('#orientation').select_option('landscape');await convert(page)
        catalog=json.loads((await download(page,'#report',args.output/'catalog')).read_text());assert len(catalog['palette'])==32
        assert len(set(await page.locator('svg g text[data-code]').all_text_contents()))==32
        assert not (await vector_audit(page))['invalidCells']
        landscape=await download(page,'#pdf',args.output/'catalog')
        with fitz.open(landscape) as d:assert abs(d[0].rect.width*25.4/72-297)<.01 and abs(d[0].rect.height*25.4/72-210)<.01
        summary['32_single_character_catalog_and_A4_landscape']='passed'
        async with page.expect_popup() as event:await page.locator('#print').click()
        popup=await event.value;await expect(popup.locator('svg')).to_be_visible();await popup.close();summary['print_popup']='passed'
        await page.locator('#clearCatalog').click();await page.locator('#paper').select_option('A3');await convert(page)
        a3=await download(page,'#pdf',args.output/'A3')
        with fitz.open(a3) as d:assert abs(d[0].rect.width*25.4/72-420)<.01 and abs(d[0].rect.height*25.4/72-297)<.01
        summary['A3_landscape_vector_PDF']='passed'
        await page.locator('#font').fill('5.5');await expect(page.locator('#pdf')).to_be_disabled()
        await page.locator('#process').click();await page.locator('#cancel').click();await expect(page.locator('#pdf')).to_be_disabled()
        await convert(page);summary['dirty_cancel_retry']='passed'
        await page.set_viewport_size({'width':390,'height':844});await page.screenshot(path=str(args.output/'mobile.png'),full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        summary['mobile_layout']='passed';summary['offsiteRequests']=remote;summary['pageErrors']=errors;summary['failedRequests']=failed
        assert not remote,remote;assert not errors,errors;assert not failed,failed
        assert not any('pyodide' in u.lower() or u.endswith('.py') for u in requests)
        summary['no_Python_no_CDN']='passed';summary['status']='passed'
        (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False,indent=2));await browser.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8770/');parser.add_argument('--output',type=Path,default=Path('test-results/flow'))
    asyncio.run(main(parser.parse_args()))
