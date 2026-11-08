function name = loadModel(model)
%LOADMODEL  Load a model given its name or a path to .slx/.mdl; return its name.
%   NOT YET EXECUTED IN MATLAB.
model = char(model);
if isempty(model)
    error('nistand:model', 'Model name must not be empty.');
end
try
    h = load_system(model);
catch err
    error('nistand:model', 'Cannot load Simulink model "%s": %s', model, err.message);
end
name = get_param(h, 'Name');
if ~strcmp(get_param(name, 'BlockDiagramType'), 'model')
    error('nistand:model', '"%s" is a %s, not a model.', name, ...
        get_param(name, 'BlockDiagramType'));
end
end
