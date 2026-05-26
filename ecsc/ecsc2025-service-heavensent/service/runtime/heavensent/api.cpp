#include "../add_on/scriptbuilder/scriptbuilder.h"
#include "../add_on/scripthelper/scripthelper.h"

#include "../add_on/scriptarray/scriptarray.h"
#include "../add_on/scriptmath/scriptmath.h"
#include "../add_on/scriptmath/scriptmathcomplex.h"
#include "../add_on/scriptstdstring/scriptstdstring.h"

#include "../add_on/scriptfile/scriptfile.h"
#include "../add_on/scriptfile/scriptfilesystem.h"

#include "plusaes.h"
#include "pocketfft_hdronly.h"

// TODO: add a preprocessor guard here to lock out tracy potentially
#include "../tracy/client/TracyProfiler.hpp"
#include "../tracy/tracy/Tracy.hpp"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <string>

void as_print(const std::string &str) {
  ZoneScoped;

  fprintf(stderr, "%s", str.c_str());
}

constexpr int SAMPLE_SIZE = sizeof(float) * 2;
static_assert(SAMPLE_SIZE == 8);

CScriptArray *as_read_samples(int n) {
  ZoneScoped;

  asIScriptContext *ctx = asGetActiveContext();
  assert(ctx);
  asIScriptEngine *engine = ctx->GetEngine();
  asITypeInfo *array_complex_ti = engine->GetTypeInfoByDecl("array<complex>");

  int got = 0;
  CScriptArray *samples = CScriptArray::Create(array_complex_ti, n);
  for (int i = 0; i < n; ++i) {
    // Read 8 bytes
    uint8_t sample_data[SAMPLE_SIZE];
    int r;
    {
      ZoneScopedN("fread");
      r = fread(&sample_data, 1, SAMPLE_SIZE, stdin);
    }
    
    // Did we get another sample?
    if (r != SAMPLE_SIZE)
    {
      // Must be EOF
      assert(r == 0);
      break;
    }
    ++got;

    // Type-pun
    float components[2];
    static_assert(sizeof(components) == sizeof(sample_data));
    memcpy(&components, &sample_data, sizeof(components));

    Complex complex = Complex(components[0], components[1]);
    samples->SetValue(i, &complex);
  }

  if (got != n)
  {
    // End of file, return partial data
    samples->Resize(got);
  }

  // fprintf(stderr, "as_read_samples(n=%d)\n", n);

  return samples;
}

void as_write_samples(const CScriptArray *samples) {
  ZoneScoped;

  // TODO: check array element type
  int n = samples->GetSize();
  for (int i = 0; i < n; ++i) {
    // Decompose into R/I
    const Complex &complex = *(const Complex *)samples->At(i);
    float components[2] = {complex.r, complex.i};

    // Type-pun
    uint8_t sample_data[SAMPLE_SIZE];
    static_assert(sizeof(sample_data) == sizeof(components));
    memcpy(&sample_data, &components, sizeof(sample_data));

    // Write it out
    int r;
    {
      ZoneScopedN("fwrite");
      r = fwrite(&sample_data, 1, SAMPLE_SIZE, stdout);
    }
    assert(r == SAMPLE_SIZE);
  }
  fflush(stdout); // TODO: does this help?
  // TODO: do we need to release the array here to not leak memory?

  // fprintf(stderr, "as_write_samples(n=%d)\n", n);
}

CScriptArray *as_fft_r2c(const CScriptArray *input) {
  ZoneScoped;

  int buf_size = input->GetSize();
  assert(input->GetElementTypeId() == asTYPEID_FLOAT);

  // Have to cast the const away here because GetBuffer() is not const for
  // some reason
  float *input_data = (float *)((CScriptArray *)input)->GetBuffer();
  // FIXME: output array sizing is wrong, this outputs the half-spectrum FFT
  std::vector<std::complex<float>> output_vec(buf_size);
  pocketfft::r2c(pocketfft::shape_t{(size_t)buf_size},             // shape in
                 pocketfft::stride_t{sizeof(float)},               // stride in
                 pocketfft::stride_t{sizeof(std::complex<float>)}, // stride out
                 0,                                                // axis
                 pocketfft::FORWARD,                               // forward
                 input_data,                                       // data_in
                 output_vec.data(),                                // data_out
                 1.f,                                              // fct
                 1                                                 // nthreads
  );

  // Create output
  asIScriptContext *ctx = asGetActiveContext();
  assert(ctx);
  asIScriptEngine *engine = ctx->GetEngine();
  asITypeInfo *array_complex_ti = engine->GetTypeInfoByDecl("array<complex>");
  CScriptArray *output = CScriptArray::Create(array_complex_ti, buf_size);
  for (int i = 0; i < buf_size; ++i) {
    Complex complex = Complex(output_vec[i].real(), output_vec[i].imag());
    output->SetValue(i, &complex);
  }

  return output;
}

CScriptArray *as_ifft_c2r(const CScriptArray *input) {
  ZoneScoped;

  int buf_size = input->GetSize();
  // TODO: ensure input is array<complex>

  // Convert input
  std::vector<std::complex<float>> input_vec(buf_size);
  for (int i = 0; i < buf_size; ++i) {
    const Complex &complex = *(const Complex *)input->At(i);
    input_vec[i] = std::complex(complex.r, complex.i);
  }

  // Create output
  asIScriptContext *ctx = asGetActiveContext();
  assert(ctx);
  asIScriptEngine *engine = ctx->GetEngine();
  asITypeInfo *array_float_ti = engine->GetTypeInfoByDecl("array<float>");
  CScriptArray *output = CScriptArray::Create(array_float_ti, buf_size);
  float *output_data = (float *)output->GetBuffer();

  // Have to cast the const away here because GetBuffer() is not const for
  // some reason
  std::vector<std::complex<float>> output_vec(buf_size);
  pocketfft::c2r(pocketfft::shape_t{(size_t)buf_size},             // shape in
                 pocketfft::stride_t{sizeof(std::complex<float>)}, // stride in
                 pocketfft::stride_t{sizeof(float)},               // stride out
                 0,                                                // axis
                 pocketfft::BACKWARD,                              // forward
                 input_vec.data(),                                 // data_in
                 output_data,                                      // data_out
                 1.f,                                              // fct
                 1                                                 // nthreads
  );

  return output;
}

CScriptArray *as_encrypt(CScriptArray *_data, CScriptArray *_iv,
                          CScriptArray *_key) {
  int data_len = _data->GetSize();
  int key_len = _key->GetSize();
  int iv_len = _iv->GetSize();

  assert(iv_len == 16);
  assert(key_len == 16);

  asIScriptContext *ctx = asGetActiveContext();
  assert(ctx);
  asIScriptEngine *engine = ctx->GetEngine();

  asITypeInfo *array_int_ti = engine->GetTypeInfoByDecl("array<int>");

  std::vector<uint8_t> data(_data->GetSize());
  std::vector<uint8_t> key(_key->GetSize());
  std::vector<uint8_t> iv(_iv->GetSize());

  for (int i = 0; i < data_len; i++)
    data[i] = *(const unsigned char *)_data->At(i);

  for (int i = 0; i < key_len; i++)
    key[i] = *(const unsigned char *)_key->At(i);

  for (int i = 0; i < iv_len; i++)
    iv[i] = *(const unsigned char *)_iv->At(i);

  std::vector<uint8_t> encrypted(data);
  plusaes::crypt_ctr(encrypted.data(), encrypted.size(), key.data(), key.size(), (const unsigned char (*)[16])iv.data());

  CScriptArray *encrypted_arr = CScriptArray::Create(array_int_ti, data_len);
  for (int i = 0; i < data_len; i++)
    encrypted_arr->SetValue(i, &encrypted[i]);

  return encrypted_arr;
}


void as_prof_zone_begin_named(const std::string &name) {
#if TRACY_ENABLE
  using namespace tracy;

#if TRACY_ON_DEMAND
#error On demand profiling not supported on as_prof_zone_begin_named!
#endif

  // Prepare source location
  asIScriptContext *ctx = asGetActiveContext();
  assert(ctx);
  // Ensure there is a parent function
  assert(ctx->GetCallstackSize() >= 1);
  int caller_frame_idx = 0;
  asIScriptFunction *caller = ctx->GetFunction(caller_frame_idx);
  assert(caller->GetFuncType() == asFUNC_SCRIPT);

  int line = ctx->GetLineNumber(caller_frame_idx);
  // NB: this is not a temp pointer!
  const char *file =
      caller->GetScriptSectionName() ? caller->GetScriptSectionName() : "";
  // NB: this is a temp pointer!
  const char *decl = caller->GetDeclaration();

  const auto srcloc = Profiler::AllocSourceLocation(
      line, file, decl, name.size() != 0 ? name.c_str() : nullptr, name.size());
  TracyQueuePrepare(QueueType::ZoneBeginAllocSrcLoc);
  MemWrite(&item->zoneBegin.time, Profiler::GetTime());
  MemWrite(&item->zoneBegin.srcloc, srcloc);
  TracyQueueCommit(zoneBeginThread);
#endif
}

void as_prof_zone_begin() {
#if TRACY_ENABLE
  as_prof_zone_begin_named("");
#endif
}

void as_prof_zone_end() {
#if TRACY_ENABLE
  using namespace tracy;

#if TRACY_ON_DEMAND
#error On demand profiling not supported on as_prof_zone_end!
#endif

  TracyQueuePrepare(QueueType::ZoneEnd);
  MemWrite(&item->zoneEnd.time, Profiler::GetTime());
  TracyQueueCommit(zoneEndThread);
#endif
}

void as_prof_frame_mark() {
#if TRACY_ENABLE
  using namespace tracy;
  Profiler::SendFrameMark(nullptr);
#endif
}

void RegisterAPI(asIScriptEngine *engine) {
  // Addons
  RegisterScriptArray(engine, true); // Use as default array type
  RegisterStdString(engine);
  RegisterStdStringUtils(engine);
  RegisterScriptMath(engine);
  RegisterScriptMathComplex(engine);
  RegisterScriptDateTime(engine); // Hidden dependency for file and filesystem
  RegisterScriptFile(engine);
  RegisterScriptFileSystem(engine);

  // Core API
  int r;
  r = engine->RegisterGlobalFunction("void print(const string &in text)",
                                     asFUNCTION(as_print), asCALL_CDECL);
  assert(r >= 0);

  r = engine->RegisterGlobalFunction("array<complex> @read_samples(int num)",
                                     asFUNCTION(as_read_samples), asCALL_CDECL);
  assert(r >= 0);
  r = engine->RegisterGlobalFunction(
      "void write_samples(const array<complex> &in samples)",
      asFUNCTION(as_write_samples), asCALL_CDECL);
  assert(r >= 0);

  // FFT
  r = engine->RegisterGlobalFunction(
      "array<complex> @fft_r2c(const array<float> &in input)",
      asFUNCTION(as_fft_r2c), asCALL_CDECL);
  assert(r >= 0);
  r = engine->RegisterGlobalFunction(
      "array<float> @ifft_c2r(const array<complex> &in input)",
      asFUNCTION(as_ifft_c2r), asCALL_CDECL);
  assert(r >= 0);

  // Crypto
  r = engine->RegisterGlobalFunction("array<int> @encrypt(array<int> &in data, "
                                     "array<int> &in iv, array<int> &in key)",
                                     asFUNCTION(as_encrypt), asCALL_CDECL);
  assert(r >= 0);

  // Profiling
  r = engine->RegisterGlobalFunction(
      "void prof_zone_begin()", asFUNCTION(as_prof_zone_begin), asCALL_CDECL);
  assert(r >= 0);
  r = engine->RegisterGlobalFunction(
      "void prof_zone_begin_named(const string &in name)",
      asFUNCTION(as_prof_zone_begin_named), asCALL_CDECL);
  assert(r >= 0);
  r = engine->RegisterGlobalFunction(
      "void prof_zone_end()", asFUNCTION(as_prof_zone_end), asCALL_CDECL);
  assert(r >= 0);
  r = engine->RegisterGlobalFunction(
      "void prof_frame_mark()", asFUNCTION(as_prof_frame_mark), asCALL_CDECL);
  assert(r >= 0);
}
