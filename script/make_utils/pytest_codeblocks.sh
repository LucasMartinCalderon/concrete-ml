#!/usr/bin/env bash

set -e

TEST_DIR="/tmp/cml_codeblocks"
rm -rf "${TEST_DIR}"
mkdir -p "${TEST_DIR}"

# grep -v "^\./\." is to avoid files in .hidden_directories
MD_FILES=$(find . -type f -name "*.md" | grep -v "^\./\.")
NCPU=$(./script/make_utils/ncpus.sh)

while [ -n "$1" ]
do
   case "$1" in
        "--file" )
            shift
            MD_FILES="$1"
            NCPU=1
            ;;

        *)
            echo "Unknown param : $1"
            exit 1
            ;;
   esac
   shift
done

DEST_MDS=()

for MD_FILE in $MD_FILES
do
    DEST_MD="${TEST_DIR}/${MD_FILE}"
    NEW_DIR=$(dirname "${DEST_MD}")
    mkdir -p "$NEW_DIR"
    cp "${MD_FILE}" "${DEST_MD}"
    DEST_MDS+=("${DEST_MD}")
done

poetry run python ./script/make_utils/deactivate_docs_admonitions_for_tests.py \
    --files "${DEST_MDS[@]}"

set -x

if [ $NCPU -ne 1 ]
then
    poetry run pytest --codeblocks -svv \
        --capture=tee-sys \
        -n "${NCPU}" \
        --randomly-dont-reorganize \
        --randomly-dont-reset-seed "${TEST_DIR}"
else
    poetry run pytest --codeblocks -svv \
        --capture=tee-sys \
        --randomly-dont-reorganize \
        --randomly-dont-reset-seed "${TEST_DIR}"
fi

set +x

rm -rf "${TEST_DIR}"
