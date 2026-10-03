"""Browser smoke test against an already running local app and CDP on 9223."""
import base64
import json
import time
from pathlib import Path
from urllib.request import urlopen
import websocket


def main():
    with urlopen('http://localhost:9223/json') as response:
        tabs = json.load(response)
    tab = next(t for t in tabs if t.get('type') == 'page' and t.get('url', '').startswith('http://127.0.0.1:8781'))
    ws = websocket.create_connection(tab['webSocketDebuggerUrl'], origin='http://localhost:9223', timeout=45)
    sequence = 0
    errors = []

    def call(method, params=None):
        nonlocal sequence
        sequence += 1
        ws.send(json.dumps({'id': sequence, 'method': method, 'params': params or {}}))
        while True:
            event = json.loads(ws.recv())
            if event.get('method') == 'Runtime.exceptionThrown':
                errors.append(event['params']['exceptionDetails'])
            if event.get('id') == sequence:
                if event.get('error'):
                    raise RuntimeError(event['error'])
                return event.get('result', {})

    call('Runtime.enable')
    call('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
    call('Page.reload', {'ignoreCache': True})
    time.sleep(1)
    script = r'''(async()=>{
      const wait=async(fn)=>{const start=Date.now();while(!fn()){if(Date.now()-start>25000)throw Error('Timeout waiting for UI');await new Promise(r=>setTimeout(r,120));}};
      await wait(()=>document.querySelector('#compose'));
      document.querySelector('[data-view="chat"]').click();
      document.querySelector('#new').click();await new Promise(r=>setTimeout(r,150));
      document.querySelector('#query').value='Thẻ nhớ microSD 64GB dưới 20 USD';
      document.querySelector('#compose').requestSubmit();
      await wait(()=>document.querySelectorAll('.assistant .card').length===5);
      const firstIds=[...document.querySelectorAll('.assistant .card')].map(card=>card.dataset.productId);
      document.querySelector('#query').value='sản phẩm nào tốt nhất trong 5 cái bạn vừa gửi';
      document.querySelector('#compose').requestSubmit();
      await wait(()=>document.querySelectorAll('.assistant').length===2);
      const selected=[...document.querySelectorAll('.assistant')].at(-1).querySelectorAll('.card');
      if(selected.length!==1||!firstIds.includes(selected[0].dataset.productId))throw Error('Best product lost prior context');
      await wait(()=>[...document.querySelectorAll('.assistant .media img')].some(img=>img.naturalWidth>1));
      const amazonImages=[...document.querySelectorAll('.assistant .media img')].filter(img=>img.naturalWidth>1).length;
      const before=document.querySelectorAll('.assistant').length;
      [...document.querySelector('.assistant .card').querySelectorAll('button')].find(b=>b.textContent==='Sản phẩm tương tự').click();
      await wait(()=>document.querySelectorAll('.assistant').length>before);
      const latest=[...document.querySelectorAll('.assistant')].at(-1);
      if(!latest.textContent.includes('tương tự')||!latest.querySelectorAll('.card').length)throw Error('Similar products failed');
      latest.querySelector('.card button').click();
      await wait(()=>document.querySelector('#detail').open&&(document.querySelector('#detailbody .review')||document.querySelector('#detailbody').textContent.includes('Chưa tìm được đánh giá')));
      document.querySelector('#close').click();
      document.querySelector('[data-view="search"]').click();
      document.querySelector('#searchquery').value='dép Tiki';
      document.querySelector('#searchform').requestSubmit();
      await wait(()=>document.querySelector('#searchresults .card'));
      const searchCount=document.querySelectorAll('#searchresults .card').length;
      if(searchCount>5)throw Error('Top five exceeded');
      await wait(()=>[...document.querySelectorAll('#searchresults .media img')].some(img=>img.naturalWidth>1));
      const tikiImages=[...document.querySelectorAll('#searchresults .media img')].filter(img=>img.naturalWidth>1).length;
      document.querySelector('[data-view="reviews"]').click();
      document.querySelector('#reviewquery').value='tai nghe Shopee';
      document.querySelector('#reviewform').requestSubmit();
      await wait(()=>document.querySelector('#reviewresults .card'));
      document.querySelector('#reviewresults .card button').click();
      await wait(()=>document.querySelector('#detail').open&&document.querySelector('#detailbody .review'));
      const reviewCount=document.querySelectorAll('#detailbody .review').length;
      if(reviewCount<1)throw Error('No reviews rendered');
      document.querySelector('#close').click();
      document.querySelector('[data-view="chat"]').click();
      return {chatCards:document.querySelectorAll('.assistant .card').length,priorContext:'passed',amazonImages,searchCount,reviewCount,tikiImages,chatHeight:document.querySelector('.chat-shell').getBoundingClientRect().height};
    })()'''
    result = call('Runtime.evaluate', {'expression': script, 'awaitPromise': True, 'returnByValue': True})
    if result.get('exceptionDetails'):
        raise RuntimeError(result['exceptionDetails'])
    screenshot = call('Page.captureScreenshot', {'format': 'png'})
    Path('.runtime').mkdir(exist_ok=True)
    Path('.runtime/app-preview.png').write_bytes(base64.b64decode(screenshot['data']))
    print(json.dumps({'ui': result['result'].get('value'), 'javascript_errors': errors}, ensure_ascii=False))
    ws.close()
    if errors:
        raise RuntimeError('Browser JavaScript errors')


if __name__ == '__main__':
    main()
