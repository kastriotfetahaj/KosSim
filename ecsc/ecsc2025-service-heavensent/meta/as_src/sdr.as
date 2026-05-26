#include "backend.as"
#include "logger.as"
#include "crc32.as"

// Protocol parameters
// SYNC: with client implementation
const int SAMP_RATE = 48000;
const int BLOCK_NUM_SAMPLES = SAMP_RATE / 16;
const int SYM_RATE = 4800;
const int SPS = SAMP_RATE / SYM_RATE;
const float BANDWIDTH_HZ = 1800.f; // ~1/27th the spectrum
const int SYM_BASE = 16;
const int SYM_PER_BYTE = 2;
const float HZ_PER_LSB = BANDWIDTH_HZ / (SYM_BASE - 1);
const int[] FRAME_SYNC_SYMBOLS = { // TODO: this might not be a very good syncword
	//0xf, 0xf, 0xf, 0x0, 0x0, 0xf, 0x0, 0x0 // Barker-7 | 0
	0x0, 0x0, 0x0, 0xf, 0xf, 0x0, 0xf, 0x0, 0xf, 0xf, 0x0, 0x0, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0xf, 0x0, 0x0, 0x0, 0x0, 0x0, 0xf, 0xf, 0xf, 0x0, 0xf // 1acffc1d, individual bits
	//0x1, 0xa, 0xc, 0xf, 0xf, 0xc, 0x1, 0xd
	// Found through exhaustive enumeration of 16-bit syncwords.
	// 0xc44b, PSLR=8, Bias = -0.12
	//0xf, 0xf, 0x0, 0x0, 0x0, 0xf, 0x0, 0x0, 0x0, 0xf, 0x0, 0x0, 0xf, 0x0, 0xf, 0xf
};
const int CONTENT_BYTE_COUNT = 64;
const int FRAME_BYTE_COUNT = CONTENT_BYTE_COUNT + 4;
const int FRAME_SYMBOL_COUNT = FRAME_BYTE_COUNT * SYM_PER_BYTE;

// Helper constants
const float PI = 3.1415926535;
const complex IM = complex(0, 1);
const float EULER = 2.7182818284;

// Logging
int SDR_LOG_LEVEL = 2;
logger@ sdr_logger = new_logger("sdr", SDR_LOG_LEVEL);

// Math
complex conj(const complex &in c)
{
	return complex(c.r, -c.i);
}

float arg(const complex &in c)
{
	return atan2(c.i, c.r);
}

complex exp(const complex &in c)
{
	return complex(pow(EULER, c.r), 0) * complex(cos(c.i), sin(c.i));
}

// I/O
void write_float_samples(const array<float> &float_samples)
{
	array<complex> complex_samples;
	for (int i = 0; i < int(float_samples.length()); i += 1)
	{
		complex_samples.insertLast(complex(float_samples[i], 0.f));
	}
	write_samples(complex_samples);
}

array<complex> modulate_fm_samples(const array<float> &fm_samples, const complex &in prev_iq)
{
	array<complex> iq_samples;
	iq_samples.reserve(fm_samples.length());

	complex c = prev_iq;
	const float fm_gain = (SAMP_RATE) / (2 * PI);
	for (int i = 0; i < int(fm_samples.length()); ++i)
	{
		float freq_hz = fm_samples[i];
		float rad_per_sample = freq_hz / fm_gain;
		c *= exp(complex(0, rad_per_sample));
		iq_samples.insertLast(c);
	}

	return iq_samples;
}

bool symbol_is_valid(int8 symbol)
{
	return symbol >= 0 && symbol < SYM_BASE;
}

float freq_to_symbol(float freq_hz)
{
	return (freq_hz + BANDWIDTH_HZ / 2) / HZ_PER_LSB;
}

float symbol_to_freq(int sym)
{
	return (sym * HZ_PER_LSB) - BANDWIDTH_HZ / 2;
}

array<int> bytes_to_symbols(const array<int> &in frame_bytes)
{
	array<int> frame_symbols;
	frame_symbols.reserve(frame_symbols.length() * 2);
	for (int i = 0; i < int(frame_bytes.length()); ++i)
	{
		frame_symbols.insertLast(frame_bytes[i] >> 4);
		frame_symbols.insertLast(frame_bytes[i] & 0xf);
	}
	return frame_symbols;
}

array<int> symbols_to_bytes(const array<int> &in frame_symbols)
{
	array<int> frame_bytes;
	frame_bytes.reserve(frame_symbols.length() / 2);
	for (int i = 0; i < int(frame_symbols.length()); i += 2)
	{
		int byte = (frame_symbols[i] << 4) | frame_symbols[i + 1];
		frame_bytes.insertLast(byte);
	}
	return frame_bytes;
}

// App functionality
array<array<int>> rx_frames_symbols;
array<float> rx_frames_doppler;
array<array<int>> tx_frames_symbols;
array<float> tx_frames_doppler;

void handle_rx_frame(const array<int> &in frame, float doppler_hz)
{
	prof_zone_begin();

	// Pack symbols into bytes
	array<int> rx_bytes = symbols_to_bytes(frame);

	log_info(sdr_logger, "[rx frame] " + hexlify(rx_bytes) + ", doppler=" + doppler_hz);

	// Check CRC
	uint32 expected_crc = crc32(rx_bytes, 0, CONTENT_BYTE_COUNT);
	uint32 got_crc = unpack(rx_bytes, CONTENT_BYTE_COUNT, 4);
	if (got_crc != expected_crc)
	{
		log_error(sdr_logger, "bad crc, packet dropped. expected=" + hex(expected_crc, 4) + ", got=" + hex(got_crc, 4));
		return;
	}
	rx_bytes.removeRange(CONTENT_BYTE_COUNT, 4);
	assert(rx_bytes.length() == CONTENT_BYTE_COUNT, "received packet had unexpected length");

	// Handle
	array<int> tx_bytes = handle_frame(rx_bytes);
	float tx_doppler = -doppler_hz;

	// Append CRC
	uint32 crc = crc32(tx_bytes, 0, CONTENT_BYTE_COUNT);
	tx_bytes.resize(FRAME_BYTE_COUNT);
	pack(tx_bytes, crc, 4, CONTENT_BYTE_COUNT);
	assert(tx_bytes.length() == FRAME_BYTE_COUNT, "transmitted packet had unexpected length");

	// Unpack bytes into symbols
	log_info(sdr_logger, "[tx frame] " + hexlify(tx_bytes) + ", doppler=" + tx_doppler);
	tx_frames_symbols.insertLast(bytes_to_symbols(tx_bytes));
	tx_frames_doppler.insertLast(tx_doppler);

	prof_zone_end();
}

// Demodulation state
complex prev_rx_iq_sample;
int rx_fm_samples_start_position = -BLOCK_NUM_SAMPLES * 2; // HACK: make sure we start at zero.
int rx_fm_samples_end_position = 0;
array<float> rx_fm_samples;

// Synchronization reference
array<float> correlator_reference;
float correlator_reference_mean;
float correlator_reference_variance;
float correlator_reference_std_deviation;

int correlator_reference_fft_size;
array<complex> correlator_reference_fft;

const float correlator_threshold = 0.7f; // TODO: estimate this from noise floor?

// Synchronization state
int sync_scan_position = 0;
float fm_moving_mean = 0.f;
float fm_moving_variance = 0.f;

// Synchronization thresholding state
const int SYNC_THRESHOLD_WINDOW_SIZE = SPS; // One symbol of time. NB: this must be less than the block size.
bool sync_threshold_triggered = false;
int sync_threshold_trigger_position = 0;

int sync_best_position = 0;
float sync_best_correlation = 0.f;
float sync_best_doppler = 0.f;

// Synchronization results
array<int> sync_detections_position;
array<float> sync_detections_doppler;

// Deframing state
array<int> deframe_current_symbols;

// TX state
array<complex> tx_iq_sample_queue;

void sync_update()
{
	log_debug(sdr_logger, "sync_update @ sync_scan_position=" + sync_scan_position);
	prof_zone_begin();
	prof_zone_begin_named("correlate");
	assert(sync_scan_position == rx_fm_samples_start_position + BLOCK_NUM_SAMPLES, "sync scan start misaligned");

	// Compute the correlation for this block.
	prof_zone_begin_named("fft input prep");
	int filter_len = correlator_reference.length();
	int correlation_result_start_position = rx_fm_samples_start_position + BLOCK_NUM_SAMPLES; // FIXME generalize
	int correlation_result_sample_count = BLOCK_NUM_SAMPLES;

	// Pre-pad with F-1 samples from previous block
	array<float> correlation_samples;
	correlation_samples.reserve(correlator_reference_fft_size);
	for (int i = 0; i < filter_len - 1; ++i)
	{
		int index = correlation_result_start_position - (filter_len - 1) + i - rx_fm_samples_start_position;
		correlation_samples.insertLast(rx_fm_samples[index]);
	}
	// Add block samples
	for (int i = 0; i < correlation_result_sample_count; ++i)
	{
		int index = correlation_result_start_position + i - rx_fm_samples_start_position;
		correlation_samples.insertLast(rx_fm_samples[index]);
	}
	// Pad with zeros (shouldn't actually be necessary)
	//assert(int(correlation_samples.length()) == correlator_reference_fft_size, "unexpected FFT size");
	correlation_samples.resize(correlator_reference_fft_size);
	prof_zone_end();

	// Convolve in frequency domain by FFT'ing and multiplying
	prof_zone_begin_named("convolution");
	array<complex> @correlation_samples_fft = fft_r2c(correlation_samples);
	assert(correlator_reference_fft.length() == correlation_samples_fft.length(), "FFT size mismatch");
	for (int i = 0; i < correlator_reference_fft_size; ++i)
	{
		correlation_samples_fft[i] *= correlator_reference_fft[i];
	}
	array<float> @correlation_results = ifft_c2r(correlation_samples_fft);
	prof_zone_end();
	prof_zone_end();

	// Joint frequency, frame and timing synchronization
	prof_zone_begin_named("scan");
	for (; sync_scan_position < rx_fm_samples_end_position; ++sync_scan_position)
	{
		int last_sample_index = sync_scan_position - rx_fm_samples_start_position;
		//log_trace(sdr_logger, "sample " + sync_scan_position + " (last index " + last_sample_index + ") = " + rx_fm_samples[last_sample_index]);

		// Update moving mean and variance
		// https://jonisalonen.com/2014/efficient-and-accurate-rolling-standard-deviation/
		float old_sample = rx_fm_samples[last_sample_index - filter_len];
		float new_sample = rx_fm_samples[last_sample_index];
		float new_mean = fm_moving_mean + (new_sample - old_sample) / filter_len;
		float new_variance = fm_moving_variance + (new_sample - old_sample) * (new_sample - new_mean + old_sample - fm_moving_mean) / (filter_len - 1);
		fm_moving_mean = new_mean;
		fm_moving_variance = new_variance;

		// Avoid negative square root due to moving variance errors
		float std_deviation;
		if (fm_moving_variance >= 0.f)
		{
			std_deviation = sqrt(fm_moving_variance);
		}
		else
		{
			std_deviation = 0.f;
		}

		// Avoid division by zero
		const float std_deviation_clamp = 1.f;
		assert(correlator_reference_std_deviation > std_deviation_clamp, "standard deviation epsilon fail");
		if (abs(std_deviation) < std_deviation_clamp) // XXX: arbitrarily chosen epsilon
		{
			// Do the sign flip for good measure although we don't really need it
			std_deviation = std_deviation >= 0 ? std_deviation_clamp : -std_deviation_clamp;
		}

		// Calculate raw correlation using FFT lookup
		int correlation_index = sync_scan_position - correlation_result_start_position;
		// Divide by N here due to the FFT normalization.
		// FFT and IFFT are inverse operations so the scaling cancels, however
		// we are multiplying two FFTs together, in which case the scaling compounds instead.
		// XXX: should we use a normalized FFT instead?
		float correlation_unnormalized = correlation_results[correlation_index] / correlator_reference_fft_size;

		// Normalize
		// Since correlation_reference is zero-mean, we do not need to subtract
		// any mean-related term here as it will be zero.
		float correlation = (correlation_unnormalized / std_deviation) / filter_len;

		// Estimate Doppler based on mean preamble bias
		float doppler_est_hz = fm_moving_mean - correlator_reference_mean;

		//log_trace(sdr_logger, "correlation_unnormalized=" + correlation_unnormalized);
		//log_trace(sdr_logger, "correlation=" + correlation);
		//log_trace(sdr_logger, "std_deviation=" + std_deviation);

		// Triggering
		if (!sync_threshold_triggered)
		{
			// Look for a correlation value exceeding the trigger.
			if (correlation >= correlator_threshold)
			{
				log_debug(sdr_logger, "sync triggered (sync_scan_position=" + sync_scan_position + ")");
				//log_trace(sdr_logger, "correlation_unnormalized=" + correlation_unnormalized);
				//log_trace(sdr_logger, "correlation=" + correlation);
				//log_trace(sdr_logger, "std_deviation=" + std_deviation);
				//log_trace(sdr_logger, "fm_moving_variance=" + fm_moving_variance);

				// Trigger!
				sync_threshold_triggered = true;
				sync_threshold_trigger_position = sync_scan_position;

				// Initialize best parameters
				sync_best_correlation = correlation;
				sync_best_doppler = doppler_est_hz;
				sync_best_position = sync_scan_position;
			}
		}
		else
		{
			// We have triggered. Are we done?
			int elapsed_samples = sync_scan_position - sync_threshold_trigger_position;
			if (elapsed_samples >= SYNC_THRESHOLD_WINDOW_SIZE)
			{
				// Windowing completed. Emit our best guess!

				// Reset thresholding state.
				sync_threshold_triggered = false;

				log_debug(sdr_logger, 
					"sync complete (position=" + sync_scan_position
					+ ", sync_best_correlation=" + sync_best_correlation
					+ ", sync_best_doppler=" + sync_best_doppler
					+ ", sync_best_position=" + sync_best_position
					+ ")"
				);

				// Mark it
				// +1 to correct from "last sample in preamble" to "first data sample"
				sync_detections_position.insertLast(sync_best_position + 1);
				sync_detections_doppler.insertLast(sync_best_doppler);

				// TODO: skip to after end of frame for perf/to avoid false detections?
			}
			else
			{
				// We are in the window. Do we have a better estimate?
				if (correlation > sync_best_correlation)
				{
					// New best candidate!
					sync_best_correlation = correlation;
					sync_best_doppler = doppler_est_hz;
					sync_best_position = sync_scan_position;
				}
			}
		}
	}
	prof_zone_end();

	prof_zone_end();
}

void deframe_next_detection()
{
	// Reset
	sync_detections_position.removeAt(0);
	sync_detections_doppler.removeAt(0);
	deframe_current_symbols.removeRange(0, deframe_current_symbols.length());
}

void deframe_update()
{
	prof_zone_begin();
	while (sync_detections_position.length() > 0)
	{
		// Get parameters
		int frame_start_position = sync_detections_position[0];
		float frame_doppler = sync_detections_doppler[0];

		// Find next symbol bounds
		int next_symbol_index = int(deframe_current_symbols.length());
		int symbol_start_position = frame_start_position + SPS * next_symbol_index;
		int symbol_end_position = symbol_start_position + SPS;

		// Check if the samples for this frame/symbol are even still available
		// This can fail if overlapping frames were detected by the synchronizer
		// for example since only one frame can be deframed at a time
		if (symbol_start_position < rx_fm_samples_start_position)
		{
			log_error(sdr_logger, "warning: tried to deframe @ " + symbol_start_position
				+ " but earliest sample available is " + rx_fm_samples_start_position + ", frame dropped!");
			deframe_next_detection();
			continue;
		}

		// Sanity checks
		assert(symbol_start_position >= rx_fm_samples_start_position, "symbol start symbol lost");
		// NB less-equals is correct in case we complete sync on the last sample of a block
		assert(symbol_start_position <= rx_fm_samples_end_position, "symbol start sample implausibly out of reach");

		// Is this symbol fully reachable yet?
		if (symbol_end_position > rx_fm_samples_end_position)
		{
			// Wait for the next block
			break;
		}

		// All samples available, integrate-and-dump
		float symbol_sum = 0.f;
		int symbol_start_sample_index = symbol_start_position - rx_fm_samples_start_position;
		int symbol_end_sample_index = symbol_end_position - rx_fm_samples_start_position;

		// HACK: Skip one sample in the front and one in the back to avoid ISI issues from sub-sample
		// misalignment. This also resolves an issue with the end of the packet, although we should
		// look into what the actual problem is there in future.
		symbol_start_sample_index += 1;
		symbol_end_sample_index -= 1;
		assert(symbol_start_sample_index < symbol_end_sample_index, "negative symbol integration time");

		for (int s = symbol_start_sample_index; s < symbol_end_sample_index; ++s)
		{
			symbol_sum += rx_fm_samples[s];
		}
		int num_integration_samples = symbol_end_sample_index - symbol_start_sample_index;
		assert(symbol_end_sample_index - symbol_start_sample_index <= SPS, "symbol size mismatch");
		float symbol_mean_hz = symbol_sum / num_integration_samples;

		// Doppler correction
		float symbol_centered_hz = symbol_mean_hz - frame_doppler;

		// Apply constellation
		float symbol_soft = freq_to_symbol(symbol_centered_hz);

		// Quantize
		int symbol_hard = int(floor(symbol_soft + 0.5f));

		if (!symbol_is_valid(symbol_hard))
		{
			log_warning(sdr_logger, "received invalid symbol " + symbol_hard + ", clamping to try and save the frame");
			if (symbol_hard < 0)
			{
				symbol_hard = 0;
			}
			else
			{
				symbol_hard = SYM_BASE - 1;
			}
		}

		log_debug(sdr_logger, "deframed symbol " + next_symbol_index
			+ ", samples [ " + symbol_start_position + "; " + symbol_end_position + " ["
			+ ", symbol_soft=" + symbol_soft
			+ ", symbol_hard=" + symbol_hard);

		// Add to frame
		deframe_current_symbols.insertLast(symbol_hard);

		// Current frame is done?
		if (deframe_current_symbols.length() == FRAME_SYMBOL_COUNT)
		{
			log_debug(sdr_logger, "deframe complete");

			// Ship it!
			rx_frames_symbols.insertLast(deframe_current_symbols);
			rx_frames_doppler.insertLast(frame_doppler);

			// Advance
			deframe_next_detection();
		}
	}
	prof_zone_end();
}

void sdr_init()
{
	// Two buffers of samples
	rx_fm_samples.resize(BLOCK_NUM_SAMPLES * 2);

	// Modulate the preamble to be used for correlation
	correlator_reference.reserve(FRAME_SYNC_SYMBOLS.length() * SPS);
	for (int i = 0; i < int(FRAME_SYNC_SYMBOLS.length()); ++i)
	{
		for (int j = 0; j < SPS; ++j)
		{
			correlator_reference.insertLast(symbol_to_freq(FRAME_SYNC_SYMBOLS[i]));
		}
	}

	// Find the mean of the preamble
	float freq_sum = 0.f;
	for (int i = 0; i < int(correlator_reference.length()); ++i)
	{
		freq_sum += correlator_reference[i];
	}
	correlator_reference_mean = freq_sum / correlator_reference.length();

	// Correct the mean to be zero
	for (int i = 0; i < int(correlator_reference.length()); ++i)
	{
		correlator_reference[i] -= correlator_reference_mean;
	}

	// Find the variance (equivalent to the peak autocorrelation)
	// NB: this must happen after mean correction (or take the mean into account)!
	float var_sum = 0.f;
	for (int i = 0; i < int(correlator_reference.length()); ++i)
	{
		var_sum += correlator_reference[i] * correlator_reference[i];
	}
	correlator_reference_variance = var_sum / int(correlator_reference.length());
	correlator_reference_std_deviation = sqrt(correlator_reference_variance);

	// Correct the standard deviation to be zero
	for (int i = 0; i < int(correlator_reference.length()); ++i)
	{
		correlator_reference[i] /= correlator_reference_std_deviation;
	}

	// Prepare the FFT input by padding to the right size
	// TODO: pick a better FFT size.
	//correlator_reference_fft_size = correlator_reference.length() + BLOCK_NUM_SAMPLES - 1;
	int min_correlator_reference_fft_size = correlator_reference.length() + BLOCK_NUM_SAMPLES - 1;
	correlator_reference_fft_size = 6144;
	assert(correlator_reference_fft_size > min_correlator_reference_fft_size, "insufficient padded FFT size");
	array<float> correlator_reference_filter(correlator_reference_fft_size);
	for (int i = 0; i < int(correlator_reference.length()); ++i)
	{
		correlator_reference_filter[i] = correlator_reference[i];
	}

	// Compute the FFT
	correlator_reference_fft = fft_r2c(correlator_reference_filter);

	// Conjugate the FFT for time reversal
	for (int i = 0; i < correlator_reference_fft_size; ++i)
	{
		correlator_reference_fft[i] = conj(correlator_reference_fft[i]);
	}

	//log_trace(sdr_logger, "correlator_reference_filter=" + format_arr(correlator_reference_filter));
	//log_trace(sdr_logger, "correlator_reference_fft=" + format_arr(correlator_reference_fft));
	//log_trace(sdr_logger, "correlator_reference_mean=" + correlator_reference_mean);
	//log_trace(sdr_logger, "correlator_reference_variance=" + correlator_reference_variance);
	//log_trace(sdr_logger, "correlator_reference_std_deviation=" + correlator_reference_std_deviation);
}

void sdr_update()
{
	prof_zone_begin();

	// Read block of IQ samples
	log_debug(sdr_logger, "read block start");
	prof_zone_begin_named("read samples");
	array<complex> @rx_iq_samples = read_samples(BLOCK_NUM_SAMPLES);
	prof_zone_end();
	log_debug(sdr_logger, "read block end");

	// EOF?
	if (rx_iq_samples.length() != BLOCK_NUM_SAMPLES)
	{
		assert(rx_iq_samples.length() == 0, "Received partial block as last block, extra samples were dropped");
		exit = true;
		return;
	}

	// Dump old sample block
	// TODO: check that all referenced positions are inbounds
	rx_fm_samples.removeRange(0, BLOCK_NUM_SAMPLES);
	rx_fm_samples_start_position += BLOCK_NUM_SAMPLES;

	// Quadrature demod the next block
	prof_zone_begin_named("quadrature demod");
	const float fm_gain = (SAMP_RATE) / (2 * PI);
	for (int i = 0; i < int(rx_iq_samples.length()); ++i)
	{
		complex iq = rx_iq_samples[i];
		float fm = fm_gain * arg(iq * conj(prev_rx_iq_sample));
		rx_fm_samples.insertLast(fm);
		prev_rx_iq_sample = iq;

		//log_trace(sdr_logger, "sample " + (rx_fm_samples_end_position + i) + " @ " + (rx_fm_samples.length() - 1) + " = " + fm);
	}
	rx_fm_samples_end_position += int(rx_iq_samples.length());
	prof_zone_end();

	// Scan for frames
	sync_update();

	// Deframe frames
	deframe_update();

	// Handle received frames
	prof_zone_begin_named("handle rx frames");
	assert(rx_frames_symbols.length() == rx_frames_doppler.length(), "rx_frames_symbol/rx_frames_doppler desync");
	while (rx_frames_symbols.length() > 0)
	{
		handle_rx_frame(rx_frames_symbols[0], rx_frames_doppler[0]);
		rx_frames_symbols.removeAt(0);
		rx_frames_doppler.removeAt(0);
	}
	prof_zone_end();

	// Modulate any outgoing frames
	prof_zone_begin_named("modulate tx frames");
	assert(tx_frames_symbols.length() == tx_frames_doppler.length(), "tx_frames_symbol/tx_frames_doppler desync");
	while (tx_frames_symbols.length() > 0)
	{
		// Try to modulate a packet into the output IQ stream
		log_debug(sdr_logger, "Modulating frame...");

		// Attach the preamble
		prof_zone_begin_named("prep symbols");
		array<int> tx_frame_symbols;
		tx_frame_symbols.insertAt(tx_frame_symbols.length(), FRAME_SYNC_SYMBOLS);
		tx_frame_symbols.insertAt(tx_frame_symbols.length(), tx_frames_symbols[0]);
		prof_zone_end();

		// Convert to FM
		prof_zone_begin_named("prep FM");
		float tx_doppler = tx_frames_doppler[0];
		array<float> tx_frame_fm_samples;
		tx_frame_fm_samples.reserve(tx_frame_symbols.length() * SPS);
		for (int i = 0; i < int(tx_frame_symbols.length()); ++i)
		{
			for (int j = 0; j < SPS; ++j)
			{
				tx_frame_fm_samples.insertLast(symbol_to_freq(tx_frame_symbols[i]) + tx_doppler);
			}
		}
		prof_zone_end();

		// Modulate FM
		prof_zone_begin_named("modulate FM");
		array<complex> tx_frame_iq_samples = modulate_fm_samples(tx_frame_fm_samples, complex(1, 0));
		prof_zone_end();

		// Push into buffer
		tx_iq_sample_queue.insertAt(tx_iq_sample_queue.length(), tx_frame_iq_samples);

		// Remove from queue
		tx_frames_symbols.removeAt(0);
		tx_frames_doppler.removeAt(0);
	}
	prof_zone_end();

	// Assemble response buffer
	array<complex> tx_iq_samples;
	tx_iq_samples.reserve(BLOCK_NUM_SAMPLES);

	// Insert any samples available and remove them from the queue
	int take_count = BLOCK_NUM_SAMPLES;
	if (int(tx_iq_sample_queue.length()) < take_count)
	{
		take_count = tx_iq_sample_queue.length();
	}
	for (int i = 0; i < take_count; ++i)
	{
		tx_iq_samples.insertLast(tx_iq_sample_queue[i]);
	}
	tx_iq_sample_queue.removeRange(0, take_count);

	// Pad with silence
	tx_iq_samples.resize(BLOCK_NUM_SAMPLES);
	
	// Write it out
	prof_zone_begin_named("write samples");
	write_samples(tx_iq_samples);
	prof_zone_end();

	prof_zone_end();
}
