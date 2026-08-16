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
    files = {'realization_stats.csv': 'case_id,target,size,control,realization_id,n_ratios,mean_r\n', 'packet_stats.csv': 'case_id,target,size,control,n_realizations,n_ratios,mean_r,se_r\nplaceholder,0,1,0,2,1,0.5,0.1\n', 'transition.csv': 'case_id,target,h_c,nu,h_c_lo,h_c_hi,nu_lo,nu_hi,fit_score,stable\nplaceholder,0,1,1,0,2,0.5,2,0.5,0\n', 'stability.csv': 'case_id,target,min_size,halfwidth,h_c,nu,validation_rmse,n_groups,fit_ok\nplaceholder,0,1,1,1,1,0.1,1,0\n', 'predictions.csv': 'query_id,mean_r,se_r\nplaceholder,0.5,0.1\n', 'claims.json': '{}\n'}
    files['realization_stats.csv'] += (
        f"{manifest['case_id']},0,1,0,probe-realization,1,nan\n"
    )
    for name, content in files.items():
        (output_dir / name).write_text(content, encoding='utf-8')

if __name__ == '__main__':
    main()
