"""Shared desktop/worker entrypoint; all runtime paths are relative to the app."""
from pathlib import Path
import os
import sys

for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8', errors='replace')

for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(variable, '4')
os.environ.setdefault('HF_HUB_OFFLINE', '1')

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        from engine import worker_main
        return worker_main()
    if len(sys.argv) > 1 and sys.argv[1] == '--process':
        import argparse
        import json
        import threading
        from engine import Engine
        parser = argparse.ArgumentParser()
        parser.add_argument('--process', required=True)
        parser.add_argument('--translator', choices=['argos', 'bing', 'google'], default='argos')
        parser.add_argument('--output')
        parser.add_argument('--ppt-annotations', action='store_true')
        parser.add_argument('--domain', choices=['general','wireless'], default='general')
        parser.add_argument('--render-mode', choices=['band','overlay'], default='band')
        parser.add_argument('--source-language', choices=['en','ja'], default='en')
        parser.add_argument('--content-mode', choices=['general','anime'], default='general')
        parser.add_argument('--model', choices=['base','small'], default='base')
        parser.add_argument('--source-srt')
        parser.add_argument('--srt-encoding', choices=['utf-8-sig','cp932','gb18030'])
        parser.add_argument('--glossary', help='Local work JSON containing confirmed terms; never a credential file')
        parser.add_argument('--recognize-only', action='store_true')
        parser.add_argument('--subtitles-only', action='store_true')
        parser.add_argument('--global-understanding', action='store_true')
        parser.add_argument('--clip-start', type=float)
        parser.add_argument('--clip-end', type=float)
        args=parser.parse_args()
        from paths import app_root
        root=app_root()
        def emit(event):
            print(json.dumps(event,ensure_ascii=False),flush=True)
        options={'translator':args.translator,'model':args.model,'render_mode':args.render_mode,'domain':args.domain,'ppt_annotations':args.ppt_annotations,
                 'source_language':args.source_language,'content_mode':args.content_mode,'source_srt':args.source_srt,
                 'srt_encoding':args.srt_encoding,'recognize_only':args.recognize_only,'subtitles_only':args.subtitles_only,'global_understanding':args.global_understanding}
        if args.glossary:
            from anime import snapshot
            options['work_snapshot']=snapshot(json.loads(Path(args.glossary).read_text(encoding='utf-8-sig')))
        if args.clip_start is not None or args.clip_end is not None:
            if args.clip_start is None or args.clip_end is None:
                parser.error('--clip-start and --clip-end must be supplied together')
            options.update(clip_enabled=True, clip_start=args.clip_start, clip_end=args.clip_end)
        if args.output: options['output_root']=args.output
        result=Engine(root,emit,threading.Event()).run(args.process,options)
        print(json.dumps({'output':str(result)},ensure_ascii=False),flush=True)
        return 0
    from gui import main as gui_main
    return gui_main()

if __name__ == '__main__':
    raise SystemExit(main())
