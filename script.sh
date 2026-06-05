##!/bin/bash

main_path=/home/kathleen/90_DATA_PREPROCESS/italy_poc_bis/data/8143


for entry in "$main_path"/*
do
  echo "$entry"
  python3 translate_pdf.py "$entry"
done
