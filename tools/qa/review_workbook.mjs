import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile, FileBlob } from '@oai/artifact-tool';

// Author a reusable native XLSX style template. Python fills native XML at runtime,
// so the colleagues' workflow never depends on this Codex authoring runtime.
const [mode, path, outputDir] = process.argv.slice(2);
if (mode === 'template') {
  const wb = Workbook.create();
  for (const name of ['審核目錄','審核卡','群組參考','系統資料']) {
    const s = wb.worksheets.add(name);
    s.showGridLines = false;
    s.getRange('A1:D10').format.font.name = 'Arial';
    s.getRange('A1:D10').format.font.size = 12;
    s.getRange('A1:A10').format.columnWidth = 23;
    s.getRange('B1:C10').format.columnWidth = 44;
    s.getRange('D1:D10').format.columnWidth = 22;
    const labels = ['標題','說明','欄位標頭','唯讀證據','比較提示','可填答案','補充理由','完成提示','跳轉連結','參考資料'];
    s.getRange('A1:A10').values = labels.map(v => [v]);
    for (let r=1; r<=10; r++) {
      const range = s.getRange(`A${r}:D${r}`);
      range.format.rowHeight = r===7 ? 90 : 30;
      range.format.wrapText = true;
      range.format.verticalAlignment = 'center';
    }
    s.getRange('A1:D1').format.fill = '#234C59';
    s.getRange('A1:D1').format.font.color = '#FFFFFF';
    s.getRange('A1:D1').format.font.size = 18;
    s.getRange('A1:D1').format.font.bold = true;
    s.getRange('A2:D2').format.fill = '#F0F4F5';
    s.getRange('A3:D3').format.fill = '#DDE9ED';
    s.getRange('A3:D3').format.font.bold = true;
    s.getRange('A4:D4').format.fill = '#FFFFFF';
    s.getRange('A5:D5').format.fill = '#E9F2EC';
    s.getRange('A6:D7').format.fill = '#FFF1CC';
    s.getRange('A6:D7').format.font.color = '#164DA0';
    s.getRange('A8:D8').format.fill = '#F0F4F5';
    s.getRange('A9:D9').format.font.color = '#176AAD';
    s.getRange('A9:D9').format.font.underline = 'single';
    s.getRange('A10:D10').format.fill = '#F7F8FA';
  }
  wb.recalculate();
  await (await SpreadsheetFile.exportXlsx(wb)).save(path);
} else if (mode === 'verify') {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  wb.recalculate();
  console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:15},maxChars:2500})).ndjson);
  await fs.mkdir(outputDir, {recursive:true});
  for (const [name,range,label] of [['審核目錄','A1:D16'],['審核卡','A1:D36'],['審核卡','A41:D76','親子審核卡'],['審核卡','A81:D116','成人審核卡'],['群組參考','A1:D15'],['系統資料','A1:D7']]) {
    const blob = await wb.render({sheetName:name,range,scale:1.5,format:'png'});
    await fs.writeFile(`${outputDir}/${label||name}.png`,new Uint8Array(await blob.arrayBuffer()));
  }
  // Exercise completion prerequisites in a disposable in-memory workbook.
  const cards=wb.worksheets.getItem('審核卡');
  for (const [cell,value] of [['B28','確認相同'],['B29','問卷資料比較'],['B30','合成測試理由']]) {
    cards.getRange(cell).values=[[value]];
    wb.recalculate();
    console.log(JSON.stringify({changedCell:cell,status:cards.getRange('B32').values}));
  }
}
