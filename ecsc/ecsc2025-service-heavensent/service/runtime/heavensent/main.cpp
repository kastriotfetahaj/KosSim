#include "api.h"

#include <iostream>  // cout
#include <assert.h>  // assert()
#include <string.h>  // strstr()
#include <angelscript.h>
#include "../add_on/scriptbuilder/scriptbuilder.h"
#include "../add_on/scripthelper/scripthelper.h"
#include <stdio.h>
#include <stdlib.h>
#include <sstream>
#include <fstream>
#if defined(_MSC_VER) && !defined(_WIN32_WCE)
#include <direct.h>
#include <crtdbg.h>
#endif
#ifdef _WIN32_WCE
#include <windows.h> // For GetModuleFileName
#endif

#include <filesystem>

using namespace std;

// Function prototypes
int ConfigureEngine(asIScriptEngine *engine, const char *configFile);
int CompileScript(asIScriptEngine *engine, const char *scriptFile);
int SaveBytecode(asIScriptEngine *engine, const char *outputFile);
int LoadBytecode(asIScriptEngine *engine, const char *inputFile);
void RunBytecode(asIScriptEngine *engine);
static const char *GetCurrentDir(char *buf, size_t size);

void MessageCallback(const asSMessageInfo *msg, void *param)
{
	const char *type = "ERR ";
	if( msg->type == asMSGTYPE_WARNING ) 
		type = "WARN";
	else if( msg->type == asMSGTYPE_INFORMATION ) 
		type = "INFO";

	fprintf(stderr, "%s (%d, %d) : %s : %s\n", msg->section, msg->row, msg->col, type, msg->message);
}

int main(int argc, char **argv)
{
#if defined(_MSC_VER)
	// Turn on memory leak detection (use _CrtSetBreakAlloc to break at specific allocation)
	_CrtSetDbgFlag(_CRTDBG_LEAK_CHECK_DF|_CRTDBG_ALLOC_MEM_DF);
	_CrtSetReportMode(_CRT_ASSERT,_CRTDBG_MODE_FILE);
	_CrtSetReportFile(_CRT_ASSERT,_CRTDBG_FILE_STDERR);

	//_CrtSetBreakAlloc(6150);
#endif

	int r;

	if( argc < 2 )
	{
		cout << "Usage: " << endl;
		cout << "heavensent <script source or binary>" << endl;
		return -1;
	}
	filesystem::path script_path = argv[1];

	// Create the script engine
	asIScriptEngine *engine = asCreateScriptEngine();
	if( engine == 0 )
	{
		cout << "Failed to create script engine." << endl;
		return -1;
	}

	// The script compiler will send any compiler messages to the callback
	engine->SetMessageCallback(asFUNCTION(MessageCallback), 0, asCALL_CDECL);

	// Register API
	RegisterAPI(engine);
	
	// If it is source code, compile it
	if (script_path.extension() == ".as")
	{
		// Compile the script code
		r = CompileScript(engine, script_path.c_str());
		if( r < 0 ) return -1;

		// Save the bytecode
		r = SaveBytecode(engine, script_path.replace_extension(".bin").c_str());
		if( r < 0 ) return -1;
	}
	else
	{
		r = LoadBytecode(engine, script_path.c_str());
		if ( r < 0 ) return -1;
	}

	// Run it
	RunBytecode(engine);

	// Shut down the engine
	engine->ShutDownAndRelease();

	return 0;
}

#ifdef AS_CAN_USE_CPP11
// The string factory doesn't need to keep a specific order in the
// cache, so the unordered_map is faster than the ordinary map
#include <unordered_map>  // std::unordered_map
BEGIN_AS_NAMESPACE
typedef unordered_map<string, int> map_t;
END_AS_NAMESPACE
#else
#include <map>      // std::map
BEGIN_AS_NAMESPACE
typedef map<string, int> map_t;
END_AS_NAMESPACE
#endif

// Default string factory. Removes duplicate string constants
// This same implementation is provided in the scriptstdstring add-on
class CStdStringFactory : public asIStringFactory
{
public:
	CStdStringFactory() {}
	~CStdStringFactory()
	{
		// The script engine must release each string 
		// constant that it has requested
		assert(stringCache.size() == 0);
	}

	const void *GetStringConstant(const char *data, asUINT length)
	{
		string str(data, length);
		map_t::iterator it = stringCache.find(str);
		if (it != stringCache.end())
			it->second++;
		else
			it = stringCache.insert(map_t::value_type(str, 1)).first;

		return reinterpret_cast<const void*>(&it->first);
	}

	int  ReleaseStringConstant(const void *str)
	{
		if (str == 0)
			return asERROR;

		map_t::iterator it = stringCache.find(*reinterpret_cast<const string*>(str));
		if (it == stringCache.end())
			return asERROR;

		it->second--;
		if (it->second == 0)
			stringCache.erase(it);
		return asSUCCESS;
	}

	int  GetRawStringData(const void *str, char *data, asUINT *length) const
	{
		if (str == 0)
			return asERROR;

		if (length)
			*length = (asUINT)reinterpret_cast<const string*>(str)->length();

		if (data)
			memcpy(data, reinterpret_cast<const string*>(str)->c_str(), reinterpret_cast<const string*>(str)->length());

		return asSUCCESS;
	}

	// TODO: Make sure the access to the string cache is thread safe
	map_t stringCache;
};

CStdStringFactory stringFactory;

int CompileScript(asIScriptEngine *engine, const char *scriptFile)
{
	int r;

	CScriptBuilder builder;
	r = builder.StartNewModule(engine, "build");
	if( r < 0 ) return -1;

	r = builder.AddSectionFromFile(scriptFile);
	if( r < 0 ) return -1;

	r = builder.BuildModule();
	if( r < 0 )
	{
		engine->WriteMessage(scriptFile, 0, 0, asMSGTYPE_ERROR, "Script failed to build");
		return -1;
	}

	engine->WriteMessage(scriptFile, 0, 0, asMSGTYPE_INFORMATION, "Script successfully built");

	return 0;
}

class CBytecodeStream : public asIBinaryStream
{
public:
	CBytecodeStream() {f = 0;}
	~CBytecodeStream() { if( f ) fclose(f); }

	int Open(const char *filename, const char *mode)
	{
		if( f ) return -1;
#if _MSC_VER >= 1500
		fopen_s(&f, filename, mode);
#else
		f = fopen(filename, mode);
#endif
		if( f == 0 ) return -1;
		return 0;
	}
	int Write(const void *ptr, asUINT size) 
	{
		if( size == 0 || f == 0 ) return 0; 
		fwrite(ptr, 1, size, f); 
		return 0;
	}
	int Read(void *ptr, asUINT size)
	{
		if ( size == 0 || f == 0 ) return 0;
		int r = fread(ptr, 1, size, f);
		assert(r == size);
		return 0;
	}

protected:
	FILE *f;
};

int SaveBytecode(asIScriptEngine *engine, const char *outputFile)
{
	CBytecodeStream stream;
	int r = stream.Open(outputFile, "wb");
	if( r < 0 )
	{
		engine->WriteMessage(outputFile, 0, 0, asMSGTYPE_ERROR, "Failed to open output file for writing");
		return -1;
	}

	asIScriptModule *mod = engine->GetModule("build");
	if( mod == 0 )
	{
		engine->WriteMessage(outputFile, 0, 0, asMSGTYPE_ERROR, "Failed to retrieve the compiled bytecode");
		return -1;
	}

	r = mod->SaveByteCode(&stream, false); // Don't strip debug info
	if( r < 0 )
	{
		engine->WriteMessage(outputFile, 0, 0, asMSGTYPE_ERROR, "Failed to write the bytecode");
		return -1;
	}

	engine->WriteMessage(outputFile, 0, 0, asMSGTYPE_INFORMATION, "Bytecode successfully saved");

	return 0;
}

int LoadBytecode(asIScriptEngine *engine, const char *inputFile)
{
	CBytecodeStream stream;
	int r = stream.Open(inputFile, "rb");
	if( r < 0 )
	{
		engine->WriteMessage(inputFile, 0, 0, asMSGTYPE_ERROR, "Failed to open input file for reading");
		return -1;
	}

	// Create module
	asIScriptModule *mod = engine->GetModule("build", asGM_ALWAYS_CREATE);
	if( mod == 0 )
	{
		engine->WriteMessage(inputFile, 0, 0, asMSGTYPE_ERROR, "Failed to create the module to read the bytecode into");
		return -1;
	}

	// Load bytecode
	bool wasDebugInfoStripped = false;
	r = mod->LoadByteCode(&stream, &wasDebugInfoStripped);
	if( r < 0 )
	{
		engine->WriteMessage(inputFile, 0, 0, asMSGTYPE_ERROR, "Failed to read the bytecode");
		return -1;
	}

	engine->WriteMessage(inputFile, 0, 0, asMSGTYPE_INFORMATION, "Bytecode successfully loaded");

	return 0;
}

void RunBytecode(asIScriptEngine *engine)
{
	asIScriptModule *mod = engine->GetModule("build");
	asIScriptFunction *func = mod->GetFunctionByDecl("void main()");
	if (func == nullptr)
	{
		fprintf(stderr, "Failed to locate main function\n");
		return;
	}

	asIScriptContext *ctx = engine->CreateContext();
	ctx->Prepare(func);
	int r = ctx->Execute();
	if (r != asEXECUTION_FINISHED)
	{
		fprintf(stderr, "Execution unfinished.\n");
		if (r == asEXECUTION_EXCEPTION)
		{
#if 1
			fprintf(stderr, "An exception occurred:\n");
			fprintf(stderr, "%s\n", GetExceptionInfo(ctx, true).c_str());
#else
			fprintf(stderr, "An exception '%s' occurred.\n", ctx->GetExceptionString());
#endif
		}
	}

	// Cleanup
	ctx->Release();
}

static const char *GetCurrentDir(char *buf, size_t size)
{
#ifdef _MSC_VER
#ifdef _WIN32_WCE
    static TCHAR apppath[MAX_PATH] = TEXT("");
    if (!apppath[0])
    {
        GetModuleFileName(NULL, apppath, MAX_PATH);

        
        int appLen = _tcslen(apppath);

        // Look for the last backslash in the path, which would be the end
        // of the path itself and the start of the filename.  We only want
        // the path part of the exe's full-path filename
        // Safety is that we make sure not to walk off the front of the 
        // array (in case the path is nothing more than a filename)
        while (appLen > 1)
        {
            if (apppath[appLen-1] == TEXT('\\'))
                break;
            appLen--;
        }

        // Terminate the string after the trailing backslash
        apppath[appLen] = TEXT('\0');
    }
#ifdef _UNICODE
    wcstombs(buf, apppath, min(size, wcslen(apppath)*sizeof(wchar_t)));
#else
    memcpy(buf, apppath, min(size, strlen(apppath)));
#endif

    return buf;
#else
	return _getcwd(buf, (int)size);
#endif
#elif defined(__APPLE__)
	return getcwd(buf, size);
#else
	return "";
#endif
}


