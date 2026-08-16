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
    manifest = json.loads((input_dir / 'manifest.json').read_text(encoding='utf-8'))
    files = {'realization_stats.csv': 'case_id,target,size,control,realization_id,n_ratios,mean_r\n', 'packet_stats.csv': 'case_id,target,size,control,n_realizations,n_ratios,mean_r,se_r\n', 'transition.csv': 'case_id,target,h_c,nu,h_c_lo,h_c_hi,nu_lo,nu_hi,fit_score,stable\n', 'stability.csv': 'case_id,target,min_size,halfwidth,h_c,nu,validation_rmse,n_groups,fit_ok\n', 'predictions.csv': 'query_id,mean_r,se_r\n'}
    files['claims.json'] = ' ' * (int(manifest['resource_contract']['output_bytes']) + 1)
    for name, content in files.items():
        (output_dir / name).write_text(content, encoding='utf-8')

if __name__ == '__main__':
    main()
