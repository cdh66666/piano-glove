"""Reproducible extraction coverage, not musical accuracy certification."""
import argparse
import json
from pathlib import Path
from score_converter import recognize_pdf, export_reviewed

def main():
    p=argparse.ArgumentParser();p.add_argument('samples',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for source in sorted(args.samples.glob('*.pdf')):
        try:
            project=recognize_pdf(source)
            row=dict(file=source.name,sha256=project['source_sha256'],**project['report'])
            try:
                export_reviewed(project)
                row['unreviewed_export_rejected']=False
            except ValueError:
                row['unreviewed_export_rejected']=True
            (args.output/(source.stem+'.review.json')).write_text(json.dumps(project,ensure_ascii=False),encoding='utf-8')
        except Exception as exc:
            row=dict(file=source.name,error=str(exc))
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    result=dict(files=len(rows),rows=rows)
    for key in ('pages','candidates','right_candidates','right_complete_fields','right_section_complete_fields','unresolved_hand','unsupported_pages'):
        result[key]=sum(r.get(key,0) for r in rows)
    result['files_with_candidates']=sum(r.get('candidates',0)>0 for r in rows)
    result['automatic_executable_files']=0
    result['accuracy']='Not measured across the complete scores; extraction coverage is not accuracy.'
    (args.output/'batch-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__':main()
