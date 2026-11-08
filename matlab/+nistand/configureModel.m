function configureModel(model, opts)
%NISTAND.CONFIGUREMODEL  Apply the ni-stand code-generation settings to a model.
%
%   nistand.configureModel(model)
%   nistand.configureModel(model, 'StepSize', 0.1)
%   nistand.configureModel(model, 'StepSize', 0.1, 'Save', false)
%
%   Sets: ERT target, fixed-step discrete single-tasking solver, nonreusable
%   (single-instance) code with root I/O as <model>_U / <model>_Y global
%   structs, model_initialize/step/terminate entry points, no example main,
%   no MAT-file logging, generate-code-only, x86-64 Linux production hardware.
%   Every value is read back; any setting that does not stick is reported
%   and the function errors before saving.
%
%   StepSize (seconds) defaults to keeping the model's current numeric
%   FixedStep; it errors if the current value is 'auto'.
%
%   Requires MATLAB R2020b+, Simulink, Simulink Coder and Embedded Coder.
%
%   NOT YET EXECUTED IN MATLAB. Written without a MATLAB license; see
%   matlab/README.md for unvalidated model-generation limitations.

arguments
    model {mustBeTextScalar}
    opts.StepSize double {mustBeScalarOrEmpty, mustBePositive, mustBeFinite} = []
    opts.Save (1,1) logical = true
end

name = loadModel(model);

cs = getActiveConfigSet(name);
if isa(cs, 'Simulink.ConfigSetRef')
    error('nistand:configRef', ['Model "%s" uses a referenced configuration set (%s). ' ...
        'Apply the ni-stand settings to the referenced Simulink.ConfigSet in its data ' ...
        'source, or convert it to a local configuration, then re-run.'], ...
        name, get_param(cs, 'Name'));
end

if isempty(opts.StepSize)
    current = str2double(get_param(name, 'FixedStep'));
    if ~(isfinite(current) && current > 0)
        error('nistand:stepSize', ['Model "%s" has FixedStep "%s". Pass ''StepSize'', ' ...
            '<seconds> (e.g. 0.1 for the sim-bench profile''s 100 ms period).'], ...
            name, get_param(name, 'FixedStep'));
    end
    stepStr = get_param(name, 'FixedStep');
else
    stepStr = mat2str(opts.StepSize);
end

% Order matters: the ERT target must be selected before ERT-only
% parameters (identifier rules, GenerateSampleERTMain) exist, and the
% solver type before the solver name. Doc URLs are in the guide.
settings = {
    'SystemTargetFile',         'ert.tlc'
    'SolverType',               'Fixed-step'
    'Solver',                   'FixedStepDiscrete'
    'FixedStep',                stepStr
    'EnableMultiTasking',       'off'
    'ProdHWDeviceType',         'Intel->x86-64 (Linux 64)'
    'ProdEqTarget',             'on'
    'CodeInterfacePackaging',   'Nonreusable function'
    'CombineOutputUpdateFcns',  'on'      % one <model>_step, not _output/_update
    'IncludeMdlTerminateFcn',   'on'      % <model>_terminate
    'GenerateSampleERTMain',    'off'     % the stand supplies main()
    'MatFileLogging',           'off'
    'ExtMode',                  'off'
    'SupportContinuousTime',    'off'
    'SupportNonFinite',         'on'      % NaN/Inf sensor values must be detectable
    'GenCodeOnly',              'on'      % compiled on the stand, not here
    'GenerateReport',           'off'
    'InternalIdentifier',       'Shortened'   % ExtU / ExtY type tokens
    'CustomSymbolStrGlobalVar', '$R$N$M'      % -> <model>_U, <model>_Y
    'CustomSymbolStrType',      '$N$R$M_T'    % -> ExtU_<model>_T, ExtY_<model>_T
    'CustomSymbolStrField',     '$N$M'        % struct fields keep port names
    };

% Identifiers longer than MaxIdLength are truncated/mangled; make sure
% ExtU_<model>_T and <model>_initialize fit. Never reduce a larger value.
needed = max(63, numel(name) + numel('_initialize') + 8);
if needed > 2048
    error('nistand:name', 'Model name "%s" is too long for generated identifiers.', name);
end
curMax = get_param(name, 'MaxIdLength');
if ischar(curMax), curMax = str2double(curMax); end
if curMax < needed
    settings(end+1, :) = {'MaxIdLength', needed};
end

failures = {};
for k = 1:size(settings, 1)
    [p, v] = settings{k, :};
    try
        set_param(name, p, v);
    catch err
        failures{end+1} = sprintf('  %s = %s: set_param failed: %s', p, toText(v), err.message); %#ok<AGROW>
        continue
    end
    try
        got = get_param(name, p);
    catch err
        failures{end+1} = sprintf('  %s: get_param failed: %s', p, err.message); %#ok<AGROW>
        continue
    end
    if ~sameValue(got, v)
        failures{end+1} = sprintf('  %s: wanted %s, model reports %s', p, toText(v), toText(got)); %#ok<AGROW>
    end
end

if ~isempty(failures)
    error('nistand:configure', ['Could not apply the ni-stand settings to "%s" ' ...
        '(model NOT saved):\n%s\nCheck that Simulink Coder and Embedded Coder are ' ...
        'installed and licensed (ert.tlc needs Embedded Coder).'], ...
        name, strjoin(failures, newline));
end

if opts.Save
    save_system(name);
end
fprintf('nistand: configured "%s" for the stand (FixedStep %s s)%s.\n', ...
    name, stepStr, ternary(opts.Save, ', saved', ', NOT saved'));
end

function tf = sameValue(got, want)
if isnumeric(want) || isnumeric(got)
    tf = isequal(double(toNum(got)), double(toNum(want)));
else
    tf = strcmp(char(got), char(want));
end
end

function n = toNum(x)
if ischar(x) || isstring(x), n = str2double(x); else, n = x; end
end

function s = toText(v)
if isnumeric(v) || islogical(v), s = mat2str(v); else, s = ['''' char(v) '''']; end
end

function out = ternary(c, a, b)
if c, out = a; else, out = b; end
end
