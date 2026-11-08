function zipPath = package(model, opts)
%NISTAND.PACKAGE  Generate ERT code for a model and package it for the stand.
%
%   zipPath = nistand.package(model)
%   zipPath = nistand.package(model, 'OutputDir', 'C:\work\out', 'StepSize', 0.1)
%   zipPath = nistand.package(model, 'Configure', false)
%
%   1. nistand.configureModel (skip with 'Configure', false)
%   2. nistand.checkInterface (errors with every problem found)
%   3. slbuild (code generation only; the stand compiles)
%   4. verifies the generated header really declares <model>_U/_Y,
%      ExtU_/ExtY_<model>_T with the contract fields, and
%      <model>_initialize/_step/_terminate(void)
%   5. packNGo flat zip, minus any sample main (ert_main.c / rt_main.c)
%   6. adds ni-stand-manifest.json at the zip root
%
%   Output: <OutputDir>/<model>-ni-stand.zip (OutputDir defaults to pwd).
%   Generated archive for separate review; not a deployment artifact.
%
%   NOT YET EXECUTED IN MATLAB. Written without a MATLAB license; see
%   matlab/README.md for unvalidated model-generation limitations.

arguments
    model {mustBeTextScalar}
    opts.OutputDir {mustBeTextScalar} = pwd
    opts.StepSize double {mustBeScalarOrEmpty, mustBePositive, mustBeFinite} = []
    opts.Configure (1,1) logical = true
end

c = nistand.contract();
name = loadModel(model);
outDir = char(opts.OutputDir);
if ~isfolder(outDir)
    error('nistand:outputDir', 'OutputDir "%s" does not exist.', outDir);
end
outDir = absPath(outDir);

if opts.Configure
    nistand.configureModel(name, 'StepSize', opts.StepSize);
end
report = nistand.checkInterface(name);

fprintf('nistand: generating code for "%s"...\n', name);
slbuild(name);

bd = RTW.getBuildDir(name);
buildDir = bd.BuildDirectory;
verifyGeneratedHeaders(buildDir, name, c);

stage = tempname;
mkdir(stage);
cleanup = onCleanup(@() rmdir(stage, 's'));

% packNGo needs the buildInfo object saved by the build.
biFile = fullfile(buildDir, 'buildInfo.mat');
if ~isfile(biFile)
    error('nistand:buildInfo', 'No buildInfo.mat in %s; did code generation finish?', buildDir);
end
bi = load(biFile, 'buildInfo');
pngZip = fullfile(stage, 'packngo.zip');
packNGo(bi.buildInfo, 'packType', 'flat', 'fileName', pngZip, 'nestedZipFiles', false);

files = fullfile(stage, 'files');
mkdir(files);
entries = unzip(pngZip, files);
rel = cellfun(@(f) f(numel(files) + 2:end), entries, 'UniformOutput', false);
if any(contains(rel, {'/', '\'}))
    error('nistand:packNGo', 'packNGo produced a non-flat zip:\n  %s', strjoin(rel, '\n  '));
end
if any(strcmp(rel, c.manifestName))
    error('nistand:packNGo', 'Generated code already contains a file named %s.', c.manifestName);
end
for m = {'ert_main.c', 'rt_main.c', 'ert_main.cpp', 'rt_cppclass_main.cpp'}
    f = fullfile(files, m{1});
    if isfile(f)
        delete(f);
        rel(strcmp(rel, m{1})) = [];
        fprintf('nistand: dropped %s (the stand provides main()).\n', m{1});
    end
end

manifest = struct( ...
    'schema', c.schema, ...
    'interface', c.interface, ...
    'model', name, ...
    'fixed_step_s', report.fixed_step_s, ...
    'matlab_release', ['R' version('-release')], ...
    'generated_utc', char(datetime('now', 'TimeZone', 'UTC', ...
        'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z''')), ...
    'generator', c.generator);
fid = fopen(fullfile(files, c.manifestName), 'w', 'n', 'UTF-8');
if fid < 0
    error('nistand:manifest', 'Cannot write %s in %s.', c.manifestName, files);
end
fwrite(fid, jsonencode(manifest), 'char');
fclose(fid);

zipPath = fullfile(outDir, [name '-ni-stand.zip']);
if isfile(zipPath)
    delete(zipPath);
end
zip(zipPath, [rel(:); {c.manifestName}], files);
clear cleanup

fprintf('nistand: wrote %s (%d files, step %g s).\n', zipPath, numel(rel) + 1, report.fixed_step_s);
fprintf('nistand: generated archive for separate review only; no deployment helper is included.\n');
end

function verifyGeneratedHeaders(buildDir, name, c)
hdrs = dir(fullfile(buildDir, '*.h'));
txt = '';
for k = 1:numel(hdrs)
    txt = [txt newline fileread(fullfile(buildDir, hdrs(k).name))]; %#ok<AGROW>
end
n = regexptranslate('escape', name);
problems = {};
need = {
    ['extern\s+ExtU_' n '_T\s+' n '_U\s*;'],            [name '_U global of type ExtU_' name '_T']
    ['extern\s+ExtY_' n '_T\s+' n '_Y\s*;'],            [name '_Y global of type ExtY_' name '_T']
    ['\<void\s+' n '_initialize\s*\(\s*void\s*\)'],     ['void ' name '_initialize(void)']
    ['\<void\s+' n '_step\s*\(\s*void\s*\)'],           ['void ' name '_step(void)']
    ['\<void\s+' n '_terminate\s*\(\s*void\s*\)'],      ['void ' name '_terminate(void)']
    };
for k = 1:size(need, 1)
    if isempty(regexp(txt, need{k, 1}, 'once'))
        problems{end+1} = need{k, 2}; %#ok<AGROW>
    end
end
problems = [problems, checkStruct(txt, ['ExtU_' n '_T'], c.inports, c)];
problems = [problems, checkStruct(txt, ['ExtY_' n '_T'], c.outports, c)];
if ~isempty(problems)
    error('nistand:generated', ['Generated headers in %s do not match the stand ABI. Missing:\n  - %s\n' ...
        'Check Code Mappings (root ports must use the default storage class, entry ' ...
        'points their default names) and the identifier settings applied by configureModel.'], ...
        buildDir, strjoin(problems, [newline '  - ']));
end
end

function problems = checkStruct(txt, typeRe, ports, c)
problems = {};
body = regexp(txt, ['typedef\s+struct\s*\w*\s*\{([^}]*)\}\s*' typeRe '\s*;'], 'tokens', 'once');
if isempty(body)
    problems{1} = ['typedef struct { ... } ' strrep(typeRe, '\', '')];
    return
end
for k = 1:numel(ports)
    ctype = c.ctype(ports(k).type);
    if isempty(regexp(body{1}, ['\<' ctype '\s+' ports(k).name '\s*;'], 'once'))
        problems{end+1} = sprintf('field "%s %s;" in %s', ctype, ports(k).name, strrep(typeRe, '\', '')); %#ok<AGROW>
    end
end
end

function p = absPath(p)
% Resolve relative paths against pwd without requiring Java.
if ~(startsWith(p, filesep) || ~isempty(regexp(p, '^[A-Za-z]:[\\/]', 'once')) || startsWith(p, '\\'))
    p = fullfile(pwd, p);
end
end
