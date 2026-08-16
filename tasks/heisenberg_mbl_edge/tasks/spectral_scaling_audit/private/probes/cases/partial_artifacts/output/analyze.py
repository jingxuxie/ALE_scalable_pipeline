import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    input_dir = Path(arguments.input)
    output_dir = Path(arguments.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'claims.json').write_text('{}\n', encoding='utf-8')

if __name__ == '__main__':
    main()
