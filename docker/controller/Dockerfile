# Builds the C runtime with the UDP plant-simulator HAL (no NI software) on
# Ubuntu 24.04; the container has no physical I/O.
FROM ubuntu:24.04 AS build
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends gcc libc6-dev make >/dev/null
WORKDIR /src
ARG MODEL=controller
COPY runtime/ /src/
# Compile the bundled synthetic model against the UDP simulator.
RUN make clean all test MODEL=${MODEL} MODEL_DIR=model/${MODEL}

FROM ubuntu:24.04
COPY --from=build /src/build/ctrl_udp /usr/local/bin/ctrl_udp
ENTRYPOINT ["/usr/local/bin/ctrl_udp"]
