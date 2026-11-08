function report = checkInterface(model, opts)
%NISTAND.CHECKINTERFACE  Validate a model against the ni-stand-io-v1 contract.
%
%   report = nistand.checkInterface(model)
%   report = nistand.checkInterface(model, 'ThrowOnError', false)
%
%   Checks, and reports ALL problems at once:
%     * root Inport/Outport blocks: exactly the contract names (any order),
%       no extra ports, no bus-element / enable / trigger ports at the root;
%     * data types: the COMPILED port data type (after an update-diagram
%       compile), so inherited types such as an Outport left at
%       'Inherit: auto' are judged by what code generation will see.
%       Root Inports must also declare their type explicitly, because a
%       root Inport's type is otherwise defined by whatever drives it in
%       simulation, not by the model;
%     * every port is a real scalar (compiled width 1);
%     * solver: fixed-step discrete, single-tasking, and exactly one
%       periodic rate (constants allowed) equal to FixedStep, offset 0;
%     * the code-generation settings the stand relies on (see configureModel).
%
%   The report struct has fields: model, ok, problems, warnings, inports,
%   outports, fixed_step_s, sample_times.
%
%   NOT YET EXECUTED IN MATLAB. Written without a MATLAB license; see
%   matlab/README.md for unvalidated model-generation limitations.

arguments
    model {mustBeTextScalar}
    opts.ThrowOnError (1,1) logical = true
end

c = nistand.contract();
name = loadModel(model);
problems = {};
warnings = {};

%% Configuration
expect = {
    'SystemTargetFile',        'ert.tlc'
    'SolverType',              'Fixed-step'
    'Solver',                  'FixedStepDiscrete'
    'EnableMultiTasking',      'off'
    'CodeInterfacePackaging',  'Nonreusable function'
    'CombineOutputUpdateFcns', 'on'
    'IncludeMdlTerminateFcn',  'on'
    'InternalIdentifier',      'Shortened'
    'CustomSymbolStrGlobalVar','$R$N$M'
    'CustomSymbolStrType',     '$N$R$M_T'
    'CustomSymbolStrField',    '$N$M'
    };
for k = 1:size(expect, 1)
    [p, v] = expect{k, :};
    try
        got = get_param(name, p);
    catch err
        problems{end+1} = sprintf('config %s: cannot read (%s)', p, err.message); %#ok<AGROW>
        continue
    end
    if ~strcmp(got, v)
        problems{end+1} = sprintf('config %s is ''%s'', expected ''%s'' (run nistand.configureModel)', p, got, v); %#ok<AGROW>
    end
end
fixedStep = str2double(get_param(name, 'FixedStep'));
if ~(isfinite(fixedStep) && fixedStep > 0)
    problems{end+1} = sprintf('config FixedStep is ''%s''; it must be a positive number of seconds', ...
        get_param(name, 'FixedStep'));
end

%% Root ports: names, structure, declared types
inBlks = find_system(name, 'SearchDepth', 1, 'BlockType', 'Inport');
outBlks = find_system(name, 'SearchDepth', 1, 'BlockType', 'Outport');
for bt = {'EnablePort', 'TriggerPort', 'ActionPort', 'ResetPort'}
    if ~isempty(find_system(name, 'SearchDepth', 1, 'BlockType', bt{1}))
        problems{end+1} = sprintf('root-level %s block is not allowed (the stand calls <model>_step every period)', bt{1}); %#ok<AGROW>
    end
end
[inBlks, problems] = checkNames(inBlks, {c.inports.name}, 'Inport', problems);
[outBlks, problems] = checkNames(outBlks, {c.outports.name}, 'Outport', problems);

for k = 1:numel(inBlks)
    blk = inBlks{k};
    want = lookupType(c.inports, get_param(blk, 'Name'));
    if isempty(want), continue, end
    declared = get_param(blk, 'OutDataTypeStr');
    if ~strcmp(declared, want)
        problems{end+1} = sprintf(['Inport %s declares data type ''%s''; set it explicitly to ''%s'' ' ...
            '(Block Parameters > Signal Attributes > Data type)'], get_param(blk, 'Name'), declared, want); %#ok<AGROW>
    end
    if isParamOn(blk, 'IsBusElementPort')
        problems{end+1} = sprintf('Inport %s is a bus element port; use a plain Inport block', get_param(blk, 'Name')); %#ok<AGROW>
    end
end
for k = 1:numel(outBlks)
    if isParamOn(outBlks{k}, 'IsBusElementPort')
        problems{end+1} = sprintf('Outport %s is a bus element port; use a plain Outport block', get_param(outBlks{k}, 'Name')); %#ok<AGROW>
    end
end

%% Sample times (getSampleTimes performs its own update diagram)
sampleTimes = [];
rate = NaN;
try
    ts = Simulink.BlockDiagram.getSampleTimes(name);
    sampleTimes = struct('value', {}, 'description', {});
    periodic = zeros(0, 2);
    for k = 1:numel(ts)
        v = ts(k).Value;
        sampleTimes(end+1) = struct('value', v, 'description', ts(k).Description); %#ok<AGROW>
        if isinf(v(1))
            continue                         % constant / parameter rates are fine
        elseif v(1) > 0
            periodic(end+1, :) = v(1:2); %#ok<AGROW>
        else
            problems{end+1} = sprintf('non-periodic sample time %s (%s): only one discrete periodic rate is supported', ...
                mat2str(v), ts(k).Description); %#ok<AGROW>
        end
    end
    if size(periodic, 1) ~= 1
        problems{end+1} = sprintf('model must be single-rate; found %d periodic rates %s', ...
            size(periodic, 1), mat2str(periodic)); %#ok<AGROW>
    else
        rate = periodic(1, 1);
        if periodic(1, 2) ~= 0
            problems{end+1} = sprintf('sample time offset %g s is not supported', periodic(1, 2)); %#ok<AGROW>
        end
        if isfinite(fixedStep) && abs(rate - fixedStep) > 1e-12 * max(1, fixedStep)
            problems{end+1} = sprintf(['model rate %g s differs from FixedStep %g s; give root Inports ' ...
                'sample time -1 or %g'], rate, fixedStep, fixedStep); %#ok<AGROW>
        end
    end
catch err
    problems{end+1} = sprintf('could not compile model to read sample times: %s', err.message);
end

%% Compiled port types and widths
inInfo = struct('name', {}, 'dataType', {}, 'width', {});
outInfo = inInfo;
compiled = false;
try
    % Equivalent to name([],[],[],'compile'); must always be paired with 'term'.
    feval(name, [], [], [], 'compile');
    compiled = true;
    [inInfo, problems] = compiledPorts(inBlks, 'Outport', c.inports, inInfo, problems);
    [outInfo, problems] = compiledPorts(outBlks, 'Inport', c.outports, outInfo, problems);
    feval(name, [], [], [], 'term');
catch err
    if compiled
        try feval(name, [], [], [], 'term'); catch, end
    end
    problems{end+1} = sprintf('model failed to compile for the port-type check: %s', err.message);
end

%% Code mappings: root I/O must stay in the default <model>_U/_Y structs
try
    cm = coder.mapping.api.get(name);
    for k = 1:numel(c.inports)
        sc = getInport(cm, c.inports(k).name, 'StorageClass');
        warnings = checkStorage(sc, 'Inport', c.inports(k).name, warnings);
    end
    for k = 1:numel(c.outports)
        sc = getOutport(cm, c.outports(k).name, 'StorageClass');
        warnings = checkStorage(sc, 'Outport', c.outports(k).name, warnings);
    end
catch
    % No code mappings yet (or older API): defaults apply. package.m
    % verifies the generated header regardless.
end

report.model = name;
report.ok = isempty(problems);
report.problems = problems(:);
report.warnings = warnings(:);
report.inports = inInfo;
report.outports = outInfo;
report.fixed_step_s = rate;
report.sample_times = sampleTimes;

for k = 1:numel(warnings)
    fprintf(2, 'nistand: warning: %s\n', warnings{k});
end
if ~report.ok && opts.ThrowOnError
    error('nistand:interface', 'Model "%s" does not satisfy %s (%d problem(s)):\n  - %s', ...
        name, c.interface, numel(problems), strjoin(problems, [newline '  - ']));
end
if report.ok
    fprintf('nistand: "%s" satisfies %s (step %g s).\n', name, c.interface, rate);
end
end

function [kept, problems] = checkNames(blks, wanted, kind, problems)
names = cellfun(@(b) get_param(b, 'Name'), blks, 'UniformOutput', false);
% Duplicated Inport blocks share a port number; keep one block per port.
ports = cellfun(@(b) str2double(get_param(b, 'Port')), blks);
[~, first] = unique(ports, 'stable');
blks = blks(first);
names = names(first);
missing = setdiff(wanted, names, 'stable');
extra = setdiff(names, wanted, 'stable');
for k = 1:numel(missing)
    hint = '';
    near = names(strcmpi(names, missing{k}) | strcmp(strtrim(names), missing{k}));
    if ~isempty(near), hint = sprintf(' (found "%s"; names are case- and space-sensitive)', near{1}); end
    problems{end+1} = sprintf('missing root %s "%s"%s', kind, missing{k}, hint); %#ok<AGROW>
end
for k = 1:numel(extra)
    problems{end+1} = sprintf('unexpected root %s "%s" (the contract allows only: %s)', ...
        kind, strrep(extra{k}, newline, '\n'), strjoin(wanted, ', ')); %#ok<AGROW>
end
kept = blks(ismember(names, wanted));
end

function t = lookupType(ports, portName)
idx = find(strcmp({ports.name}, portName), 1);
if isempty(idx), t = ''; else, t = ports(idx).type; end
end

function tf = isParamOn(blk, p)
try
    tf = strcmp(get_param(blk, p), 'on');
catch
    tf = false;                              % parameter absent in this release
end
end

function [info, problems] = compiledPorts(blks, side, ports, info, problems)
% For an Inport block the signal leaves on its Outport side, and vice versa.
for k = 1:numel(blks)
    blk = blks{k};
    portName = get_param(blk, 'Name');
    dts = get_param(blk, 'CompiledPortDataTypes');
    widths = get_param(blk, 'CompiledPortWidths');
    dt = dts.(side);
    if iscell(dt), dt = dt{1}; end
    w = widths.(side);
    w = w(1);
    info(end+1) = struct('name', portName, 'dataType', dt, 'width', w); %#ok<AGROW>
    want = lookupType(ports, portName);
    if ~strcmp(dt, want)
        problems{end+1} = sprintf('%s compiles as ''%s'', contract requires ''%s''', portName, dt, want); %#ok<AGROW>
    end
    if w ~= 1
        problems{end+1} = sprintf('%s has width %d; contract requires a scalar', portName, w); %#ok<AGROW>
    end
end
end

function warnings = checkStorage(sc, kind, portName, warnings)
if ~any(strcmp(sc, {'Auto', 'Default', 'Model default'}))
    warnings{end+1} = sprintf(['%s %s is mapped to storage class ''%s''; it will not be a field of ' ...
        'the <model>_%s struct. Set it back to Auto in the Code Mappings editor.'], ...
        kind, portName, sc, ternary(strcmp(kind, 'Inport'), 'U', 'Y'));
end
end

function out = ternary(c, a, b)
if c, out = a; else, out = b; end
end
