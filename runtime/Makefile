# Simulation-only C runtime. The sole HAL is UDP to a synthetic plant.
CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Werror
MODEL_CFLAGS ?= -O2 -std=gnu11 -w
MODEL ?= controller
MODEL_DIR ?= model/controller
OUT ?= build

MODEL_SRCS := $(filter-out %/ert_main.c,$(wildcard $(MODEL_DIR)/*.c))
MODEL_OBJS := $(patsubst $(MODEL_DIR)/%.c,$(OUT)/model/%.o,$(MODEL_SRCS))
GLUE := -I$(MODEL_DIR) -Isrc -DMODEL=$(MODEL) -DMODEL_HEADER='"$(MODEL).h"'

all: $(OUT)/ctrl_udp $(OUT)/test_controller

$(OUT)/model/%.o: $(MODEL_DIR)/%.c | $(OUT)/model
	$(CC) $(MODEL_CFLAGS) -I$(MODEL_DIR) -c -o $@ $<

$(OUT)/model:
	mkdir -p $@

$(OUT)/ctrl_udp: src/main.c src/hal_udp.c src/*.h $(MODEL_OBJS)
	$(CC) $(CFLAGS) $(GLUE) -o $@ src/main.c src/hal_udp.c $(MODEL_OBJS) -lm

$(OUT)/test_controller: tests/test_controller.c model/controller/*.c model/controller/*.h | $(OUT)/model
	$(CC) $(CFLAGS) -Imodel/controller -o $@ tests/test_controller.c model/controller/controller.c -lm

test: $(OUT)/test_controller
	$(OUT)/test_controller

clean:
	rm -rf $(OUT)

.PHONY: all test clean
