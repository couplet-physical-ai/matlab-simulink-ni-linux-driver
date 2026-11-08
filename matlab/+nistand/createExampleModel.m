function name = createExampleModel(name, opts)
%NISTAND.CREATEEXAMPLEMODEL  Build the ni-stand-io-v1 example model.
%
%   name = nistand.createExampleModel()                    % 'ni_stand_example'
%   name = nistand.createExampleModel('my_ctrl', 'StepSize', 0.1, ...
%              'OutputDir', pwd, 'Overwrite', true)
%
%   Implements the same illustrative law as runtime/model/controller/controller.c:
%     fault      = fault(k-1) OR NOT sensor_ok OR NOT isfinite(T_meas_C)  (latched)
%     running    = NOT fault
%     heater_cmd = fault ? 0 : clamp(0.1 * (T_set_C - T_meas_C), 0, 1)
%     blower_cmd = fault ? 1.0 : 0.5
%   The proportional law is a placeholder, not derived from any existing LabVIEW control loop.
%
%   One difference from controller.c: before the first step, ERT
%   initializes all outputs to 0 (controller_initialize sets blower 1.0).
%   The stand runtime calls <model>_step before it writes any output.
%
%   NOT YET EXECUTED IN MATLAB. Written without a MATLAB license; see
%   matlab/README.md for unvalidated model-generation limitations.

arguments
    name {mustBeTextScalar} = 'ni_stand_example'
    opts.StepSize (1,1) double {mustBePositive, mustBeFinite} = 0.1
    opts.OutputDir {mustBeTextScalar} = pwd
    opts.Overwrite (1,1) logical = false
end

name = char(name);
if ~isvarname(name)
    error('nistand:name', '"%s" is not a valid model name (letters, digits, underscores; start with a letter).', name);
end
file = fullfile(char(opts.OutputDir), [name '.slx']);
if bdIsLoaded(name)
    if ~opts.Overwrite
        error('nistand:exists', 'Model "%s" is already loaded. Pass ''Overwrite'', true to replace it.', name);
    end
    close_system(name, 0);
end
if (isfile(file) || exist(name, 'file') == 4) && ~opts.Overwrite
    error('nistand:exists', 'Model "%s" already exists (%s). Pass ''Overwrite'', true to replace it.', ...
        name, which(name));
end

c = nistand.contract();
ts = mat2str(opts.StepSize);
new_system(name);
m = @(blk) [name '/' blk];

% Root ports, numbered in contract order. Inports carry the model rate.
for k = 1:numel(c.inports)
    p = c.inports(k);
    add_block('simulink/Sources/In1', m(p.name), 'Port', num2str(k), ...
        'OutDataTypeStr', p.type, 'SampleTime', ts, ...
        'Position', [40, 40 + 90 * (k - 1), 70, 54 + 90 * (k - 1)]);
end
for k = 1:numel(c.outports)
    p = c.outports(k);
    add_block('simulink/Sinks/Out1', m(p.name), 'Port', num2str(k), ...
        'OutDataTypeStr', p.type, ...
        'Position', [760, 40 + 90 * (k - 1), 790, 54 + 90 * (k - 1)]);
end

% Proportional heater law: clamp(Kp * (T_set_C - T_meas_C), 0, 1)
add_block('simulink/Math Operations/Sum', m('Error'), 'Inputs', '+-', ...
    'Position', [160, 30, 190, 80]);
add_block('simulink/Math Operations/Gain', m('Kp'), 'Gain', '0.1', ...
    'Position', [240, 40, 280, 70]);
add_block('simulink/Discontinuities/Saturation', m('Clamp01'), ...
    'UpperLimit', '1', 'LowerLimit', '0', 'Position', [330, 40, 370, 70]);

% Latched fault
add_block('simulink/Logic and Bit Operations/Logical Operator', m('NotSensorOk'), ...
    'Operator', 'NOT', 'Position', [160, 125, 190, 145]);
add_block('simulink/Logic and Bit Operations/Relational Operator', m('IsFinite'), ...
    'Operator', 'isFinite', 'Position', [160, 190, 200, 220]);
add_block('simulink/Logic and Bit Operations/Logical Operator', m('NotFinite'), ...
    'Operator', 'NOT', 'Position', [240, 195, 270, 215]);
add_block('simulink/Logic and Bit Operations/Logical Operator', m('FaultLatch'), ...
    'Operator', 'OR', 'Inputs', '3', 'Position', [330, 130, 360, 230]);
add_block('simulink/Discrete/Unit Delay', m('FaultPrev'), ...
    'InitialCondition', '0', 'SampleTime', '-1', 'Position', [330, 270, 365, 300], ...
    'Orientation', 'left');

% Outputs selected by fault (Switch passes input 1 when u2 is true)
add_block('simulink/Sources/Constant', m('HeaterSafe'), 'Value', '0', ...
    'Position', [470, 20, 500, 40]);
add_block('simulink/Signal Routing/Switch', m('HeaterSwitch'), ...
    'Criteria', 'u2 ~= 0', 'Position', [580, 25, 620, 85]);
add_block('simulink/Sources/Constant', m('BlowerSafe'), 'Value', '1.0', ...
    'Position', [470, 110, 500, 130]);
add_block('simulink/Sources/Constant', m('BlowerRun'), 'Value', '0.5', ...
    'Position', [470, 170, 500, 190]);
add_block('simulink/Signal Routing/Switch', m('BlowerSwitch'), ...
    'Criteria', 'u2 ~= 0', 'Position', [580, 110, 620, 190]);
add_block('simulink/Logic and Bit Operations/Logical Operator', m('NotFault'), ...
    'Operator', 'NOT', 'Position', [580, 215, 610, 235]);

L = @(src, dst) add_line(name, src, dst, 'autorouting', 'on');
L('T_set_C/1', 'Error/1');
L('T_meas_C/1', 'Error/2');
L('Error/1', 'Kp/1');
L('Kp/1', 'Clamp01/1');
L('sensor_ok/1', 'NotSensorOk/1');
L('T_meas_C/1', 'IsFinite/1');
L('IsFinite/1', 'NotFinite/1');
L('NotSensorOk/1', 'FaultLatch/1');
L('NotFinite/1', 'FaultLatch/2');
L('FaultPrev/1', 'FaultLatch/3');
L('FaultLatch/1', 'FaultPrev/1');
L('HeaterSafe/1', 'HeaterSwitch/1');
L('FaultLatch/1', 'HeaterSwitch/2');
L('Clamp01/1', 'HeaterSwitch/3');
L('BlowerSafe/1', 'BlowerSwitch/1');
L('FaultLatch/1', 'BlowerSwitch/2');
L('BlowerRun/1', 'BlowerSwitch/3');
L('FaultLatch/1', 'NotFault/1');
L('HeaterSwitch/1', 'heater_cmd/1');
L('BlowerSwitch/1', 'blower_cmd/1');
L('NotFault/1', 'running/1');
L('FaultLatch/1', 'fault/1');

set_param(name, 'Description', ['ni-stand-io-v1 example generated by nistand.createExampleModel. ' ...
    'Illustrative proportional law mirroring runtime/model/controller/controller.c; not derived from any existing LabVIEW control loop.']);

save_system(name, file);
nistand.configureModel(name, 'StepSize', opts.StepSize);
fprintf('nistand: created %s\n', file);
end
