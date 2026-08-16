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
    (output_dir.parent / 'escape.txt').write_text('escaped', encoding='utf-8')

if __name__ == '__main__':
    main()
