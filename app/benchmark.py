"""Compatibility CLI for the current counterfactual evaluation."""
import argparse
import json
from pathlib import Path
from .evaluation import run as evaluate


def run():return evaluate(quick=True)

def run_extended():return evaluate(quick=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--extended',action='store_true')
    parser.add_argument('--output',default='docs/benchmark.json')
    args=parser.parse_args()
    data=run_extended() if args.extended else run()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(data['summary'],ensure_ascii=False,indent=2))
