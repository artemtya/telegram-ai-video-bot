@echo off
set COMMANDLINE_ARGS=--skip-torch-cuda-test --use-cpu all --no-half --precision full --disable-opt-split-attention

python -m venv venv
call venv\Scripts\activate

pip uninstall torch torchvision -y
pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cpu
pip install --prefer-binary -r requirements.txt
pip install open_clip_torch==2.20.0 --no-deps
pip install clip --no-deps

deactivate
pause