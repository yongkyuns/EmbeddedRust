/* SPDX-License-Identifier: MIT
 * Fixture-only compatibility bridge; not a production HAL interface.
 */
#ifndef RUSTCAM_NUTTX_TRANSPORT_H
#define RUSTCAM_NUTTX_TRANSPORT_H
#include <stddef.h>
#include <stdint.h>
/* Stable bridge statuses, not native errno. Success is local acceptance only. */
int rc_nx_udp_open(const uint8_t *, uint16_t);
int rc_nx_send(int, const uint8_t *, size_t);
#endif
