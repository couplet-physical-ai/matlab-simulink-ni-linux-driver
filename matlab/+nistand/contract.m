function c = contract()
%NISTAND.CONTRACT  The "ni-stand-io-v1" root I/O contract and package constants.
%
%   c = nistand.contract() returns the port names/types every stand model
%   must expose and the identifiers written into ni-stand-manifest.json.
%   The illustrative C runtime model interface is written against
%   exactly these values; do not edit them without versioning the interface.
%
%   NOT YET EXECUTED IN MATLAB. Written without a MATLAB license; see
%   matlab/README.md for unvalidated model-generation limitations.

c.interface = 'ni-stand-io-v1';
c.schema = 'ni-stand-model-v1';
c.generator = 'nistand.package';
c.manifestName = 'ni-stand-manifest.json';

% Order here is the port numbering createExampleModel uses; checkInterface
% matches by name and does not require this order.
c.inports = struct( ...
    'name', {'T_meas_C', 'sensor_ok', 'T_set_C'}, ...
    'type', {'double', 'boolean', 'double'});
c.outports = struct( ...
    'name', {'heater_cmd', 'blower_cmd', 'running', 'fault'}, ...
    'type', {'double', 'double', 'boolean', 'boolean'});

% Generated C type for each Simulink type (rtwtypes.h).
c.ctype = containers.Map({'double', 'boolean'}, {'real_T', 'boolean_T'});
end
