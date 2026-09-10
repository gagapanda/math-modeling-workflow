function ocr_selected_pages(manifestPath, outputDirectory, model)
%OCR_SELECTED_PAGES OCR prepared page images without modifying evidence files.
arguments
    manifestPath (1,1) string
    outputDirectory (1,1) string
    model (1,1) string
end
if strlength(strtrim(model)) == 0
    error('mathmodel:ocr:MissingModel', ...
        'An explicit OCR model is required; do not rely on the English default.');
end
manifest = jsondecode(fileread(manifestPath));
if manifest.schema_version ~= 1 || ~strcmp(manifest.status, 'prepared')
    error('mathmodel:ocr:InvalidManifest', ...
        'Expected a prepared schema version 1 manifest.');
end
if isfolder(outputDirectory) || isfile(outputDirectory)
    error('mathmodel:ocr:OutputExists', 'OCR output path already exists.');
end
mkdir(outputDirectory);
try
    manifestDirectory = string(fileparts(manifestPath));
    for index = 1:numel(manifest.pages)
        page = manifest.pages(index);
        imagePath = fullfile(manifestDirectory, string(page.image));
        if ~isfile(imagePath)
            error('mathmodel:ocr:MissingImage', ...
                'Prepared page image is missing: %s', imagePath);
        end
        result = ocr(imread(imagePath), Model=model, LayoutAnalysis='page');
        textPath = fullfile(outputDirectory, sprintf('page-%d.txt', page.page));
        writeText(textPath, string(result.Text));
    end
catch exception
    if isfolder(outputDirectory)
        rmdir(outputDirectory, 's');
    end
    rethrow(exception);
end
end

function writeText(path, content)
stream = fopen(path, 'w', 'n', 'UTF-8');
if stream < 0
    error('mathmodel:ocr:WriteFailed', 'Cannot open OCR output: %s', path);
end
cleanup = onCleanup(@() fclose(stream));
fprintf(stream, '%s', content);
end
