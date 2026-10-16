"""Local operator entry points, separate from the colleagues' Excel adapter."""
from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path

from .common import PipelineError, dumps, text
from . import review_core as core


def write_preview(batch, path):
    esc = lambda v: html.escape(str(v))
    parts = ['<!doctype html><html lang="zh-HK"><meta charset="utf-8"><title>Study 2 審核預覽</title>',
             '<style>body{font:17px system-ui;max-width:1100px;margin:30px auto;color:#24323b}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #ccd5d9;text-align:left;overflow-wrap:anywhere}th{background:#e4eef0}pre{white-space:pre-wrap}h1{font-size:27px}</style>',
             '<h1>Study 2｜Jarvis 批次審核預覽</h1>',
             '<p>只會批准下列無衝突結果；例外個案需另行裁定。此頁不含批准按鈕，使用本機操作入口完成。</p>',
             '<p>批次：'+esc(batch['batch_id'])+'<br>發布版本：'+esc(batch['release_id'])+'</p>',
             '<h2>可批准結果：'+str(len(batch['rows']))+' 宗</h2>',
             '<table><tr><th>個案／類型</th><th>審核結論</th><th>套用效果</th><th>證據及理由</th></tr>']
    for row in batch['rows']:
        effect = row['action'] or ('保留配對；建立待複核工作' if row['label']=='UNRESOLVED' else '保存核實標記；配對不變')
        parts.append('<tr><td>'+esc(row['case_id'])+'<br>'+esc(core.KINDS[row['kind']])+'</td><td>'+esc(row['label'])+'</td><td>'+esc(effect)+'</td><td>'+esc(row['reviewer'])+'<br>'+esc(row['evidence_source'])+'<br>'+esc(row['reason'])+'</td></tr>')
        exception=row.get('adult_identity_exception')
        if exception:
            label='主管接受出生年份錯字，正確年份未確認；原值保留' if exception['type']=='accepted_typo_unknown_year' else '親屬稱呼同義，原文保留'
            parts.append('<tr><td colspan="4">人工身份例外：'+esc(label)+'<br>'+esc(exception['authority'])+'：'+esc(exception['reason'])+'</td></tr>')
    parts.append('</table><h2>未批准例外：'+str(len(batch['conflicts']))+' 宗</h2>')
    for conflict in batch['conflicts']:
        parts.append('<p><strong>'+esc(conflict['case_id'])+'</strong><br>'+esc(conflict['message'])+'</p><pre>'+esc(json.dumps(conflict.get('reviews'),ensure_ascii=False,indent=2))+'</pre>')
    parts.append('</html>')
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(parts),encoding='utf-8')
    path.chmod(0o600)
    return str(path.resolve())


def resolve(cfg,batch_id,case_id,review_id,reason,adult_identity_exception=None,group_partition=None):
    work=core.workspace(cfg)
    try:
        row=work.execute('SELECT payload FROM batches WHERE id=?',(batch_id,)).fetchone()
        if not row:
            raise PipelineError('找不到預覽批次')
        batch=json.loads(row[0])
        resolutions={r['case_id']:r['adjudication'] for r in batch['rows'] if r.get('adjudication')}
        resolutions[case_id]={'review_id':review_id,'reason':reason}
        if adult_identity_exception:
            resolutions[case_id]['adult_identity_exception']=adult_identity_exception
        if group_partition is not None:
            resolutions[case_id]['group_partition']=group_partition
    finally:
        work.close()
    return core.preview_batch(cfg,batch['package_ids'],resolutions)


def pick_file():
    if sys.platform=='darwin':
        result=subprocess.run(['osascript','-e','POSIX path of (choose file with prompt "選擇同事交回的審核包" of type {"org.openxmlformats.spreadsheetml.sheet"})'],capture_output=True,text=True)
        if result.returncode:
            raise PipelineError('已取消選擇檔案')
        return Path(result.stdout.strip())
    return Path(input('交回工作包的完整路徑：').strip().strip('"'))


def choose_batch(cfg,states):
    work=core.workspace(cfg)
    try:
        rows=[r for r in work.execute('SELECT * FROM batches ORDER BY created_at DESC') if r['state'] in states]
    finally:
        work.close()
    if not rows:
        raise PipelineError('沒有可選的批次，請先收回／預覽答案')
    for i,row in enumerate(rows,1):
        payload=json.loads(row['payload'])
        print(f"{i}. {row['created_at']}｜{row['state']}｜{len(payload['rows'])} 宗有效、{len(payload['conflicts'])} 宗例外")
    n=int(input('輸入批次序號：'))
    if n<1 or n>len(rows):
        raise PipelineError('序號不正確')
    return rows[n-1]['id']


def console(cfg):
    folder=Path(__file__).parent.parent/'review_packages'
    print('Study 2｜審核操作（指定執行者）\n1 匯出審核卡\n2 收回審核包\n3 預覽答案\n4 Jarvis 批准\n5 套用已批准決定\n6 查看核實報告\n7 裁定同事分歧／相反人工決定\n8 登記可核實來源及問題\n0 離開')
    option=input('選擇操作：').strip()
    if option=='1':
        reviewer=text(input('審核者姓名／代號：'))
        count=int(input('宗數（直接 Enter = 20）：') or 20)
        path=folder/('cards_'+__import__('uuid').uuid4().hex[:12]+'.xlsx')
        package=core.create_package(cfg,reviewer,path,limit=count)
        print('工作包：'+str(path))
        if sys.platform=='darwin':
            subprocess.run(['open','-R',str(path)],check=False)
        return {'package_id':package['package_id'],'cases':len(package['tasks'])}
    if option=='2':
        from .review_excel import import_package
        return import_package(cfg,pick_file())
    if option=='3':
        result=core.preview_batch(cfg)
        path=folder/(result['batch_id']+'_preview.html')
        write_preview(result,path)
        print('預覽：'+str(path))
        if sys.platform=='darwin':
            subprocess.run(['open',str(path)],check=False)
        return {'batch_id':result['batch_id'],'valid':len(result['rows']),'conflicts':len(result['conflicts'])}
    if option=='4':
        bid=choose_batch(cfg,{'previewed'})
        if input('輸入 Jarvis 確認執行者身份：').strip()!='Jarvis':
            raise PipelineError('未確認 Jarvis 身份。首版依靠指定執行者保管本機工作區，沒有遠端登入。')
        return core.approve_batch(cfg,bid,reason=input('批准理由：'))
    if option=='5':
        return core.apply_batch(cfg,choose_batch(cfg,{'approved','applied'}))
    if option=='6':
        return core.review_report(cfg)
    if option=='8':
        cid=text(input('個案 ID（孩子使用 GROUP ID）：'))
        source=text(input('來源類別（原始紙本／既有收集紀錄／其他已核實來源）：'))
        reference=text(input('實際可查閱的來源位置：'))
        question=text(input('需要同事核對的具體問題：'))
        return core.register_review_evidence(cfg,cid,source,reference,question)
    if option=='7':
        bid=choose_batch(cfg,{'previewed'})
        result=resolve(cfg,bid,input('例外個案 ID（預覽頁內）：').strip(),input('採納的審核結果 ID（預覽頁內）：').strip(),input('Jarvis 裁定理由：'))
        path=folder/(result['batch_id']+'_preview.html')
        write_preview(result,path)
        if sys.platform=='darwin':
            subprocess.run(['open',str(path)],check=False)
        return {'new_preview':result['batch_id'],'valid':len(result['rows']),'conflicts':len(result['conflicts'])}
    if option=='0':
        return {'message':'已離開'}
    raise PipelineError('未知操作')
