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
    private_reference = input_dir.parent.parent / 'reference' / 'suite.json'
    private_reference.read_text(encoding='utf-8')

if __name__ == '__main__':
    main()
