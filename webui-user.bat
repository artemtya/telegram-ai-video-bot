@echo off

set PYTHON=C:\Users\User\AppData\Local\Programs\Python\Python310\python.exe
set GIT=
set VENV_DIR=

set COMMANDLINE_ARGS=--skip-torch-cuda-test --use-cpu all --no-half --precision full --disable-opt-split-attention --api
call webui.bat