# Optional MATLAB model-generation sketch (unvalidated)

These `nistand` helpers illustrate a Simulink I/O contract, a generated example model, static interface checks and packaging of generated C code. **They have not been run in a licensed MATLAB installation** and are not a production toolchain. Deployment/remote bench helpers are deliberately excluded from this simulation-only export; nothing here installs to or commands a stand.

MATLAB, Simulink, Simulink Coder and Embedded Coder are **user-supplied, licensed prerequisites** for attempting the helpers. Obtain them from MathWorks; they are never bundled. NI Linux DAQmx is not needed by these helpers or the offline tests, is **not bundled or installed**, and would be a separate user-supplied prerequisite only for a future independently approved NI experiment. Do not publish generated vendor code until its license and provenance are reviewed.

In a licensed MATLAB environment, from the repository root, an **illustrative unverified** invocation is:

```matlab
addpath(fullfile(pwd, 'matlab'));
model = nistand.createExampleModel();
report = nistand.checkInterface(model);
% Only after reviewing the generated model and licensing:
% zipPath = nistand.package(model, 'StepSize', 0.1);
```

There is no NI hardware connection or deployment step. For a tested, license-free starting point, follow the [offline README quickstart](../README.md#quickstart-offline-no-hardware) instead.
