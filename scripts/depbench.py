"""Download only metadata and task inputs. Never expose reference solutions to the agent."""
import json
from pathlib import Path
import httpx

REPO='Depbench/build_from_source'
REVISION='3eef955c222baa310ef039153755ec9d7cdb03f3'


def main():
    root=Path('data/external/depbench')
    root.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=45,follow_redirects=True) as client:
        revision=REVISION
        def fetch(path):
            r=client.get(f'https://huggingface.co/datasets/{REPO}/resolve/{revision}/{path}')
            r.raise_for_status()
            return r.text
        summary=json.loads(fetch('dataset/task_summary.json'))
        (root/'task_summary.json').write_text(json.dumps(summary,indent=2))
        (root/'repository_metadata.csv').write_text(fetch('analysis/task_repository_metadata.csv'))
        (root/'source_builds.json').write_text(fetch('analysis/task_source_builds.json'))
        selected=[t for t in summary if t['ecosystem']=='pip' or t['folder']=='chris48s__v8r__22']
        for task in selected:
            folder=task['folder']
            dest=root/folder
            dest.mkdir(exist_ok=True)
            for file in ['instruction.md','environment/Dockerfile','environment/patches/manifest.patch']:
                text=fetch('dataset/tasks/'+folder+'/'+file)
                output=dest/file
                output.parent.mkdir(parents=True,exist_ok=True)
                output.write_text(text)
        manifest={'repo':REPO,'revision':revision,'tasks':len(summary),'selected':selected,
            'protocol':'No reference solutions downloaded. Verifier files are evaluator-only; the development model receives failure summaries, not verifier source.',
            'license':'Per upstream repository; see downloaded task_repository_metadata.csv'}
        Path('research/depbench-manifest.json').write_text(json.dumps(manifest,indent=2))
        print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
