cmake_minimum_required(VERSION 3.28)
project(jit)
cmake_policy(SET CMP0135 NEW)

set(CMAKE_CXX_STANDARD 23)
LIST(APPEND CMAKE_MODULE_PATH ${PROJECT_SOURCE_DIR}/cmake)

# We suggest to build this project with clang, not g++, because it has better module support.

# JSON library
include(FetchContent)
FetchContent_Declare(json URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz)
FetchContent_MakeAvailable(json)

# ANTLR
if(NOT ANTLR4_VERSION)
	set(ANTLR4_VERSION "4.13.2")
endif()
if(NOT ANTLR4_COMMAND)
	file(DOWNLOAD "https://www.antlr.org/download/antlr-${ANTLR4_VERSION}-complete.jar" "${CMAKE_CURRENT_BINARY_DIR}/antlr4.jar")
	set(ANTLR4_COMMAND java -jar ${CMAKE_CURRENT_BINARY_DIR}/antlr4.jar)
endif()

# ANTLR runtime
set(ANTLR_BUILD_SHARED OFF)
set(ANTLR4_TAG ${ANTLR4_VERSION})
include(ExternalAntlr4Cpp)
include_directories(${ANTLR4CPP_INCLUDE_DIRS})
link_directories(${ANTLR4CPP_LIBS})


set(ANTLR_GENERATED_SOURCES
		${PROJECT_SOURCE_DIR}/src/generated/JitterishLexer.cpp
		${PROJECT_SOURCE_DIR}/src/generated/JitterishParser.cpp
		${PROJECT_SOURCE_DIR}/src/generated/JitterishBaseListener.cpp
		${PROJECT_SOURCE_DIR}/src/generated/JitterishBaseVisitor.cpp
		${PROJECT_SOURCE_DIR}/src/generated/JitterishListener.cpp
		${PROJECT_SOURCE_DIR}/src/generated/JitterishVisitor.cpp
		src/rtlib/jit_values.h
)

foreach (src_file ${ANTLR_GENERATED_SOURCES})
	set_source_files_properties(${src_file} PROPERTIES GENERATED TRUE)
endforeach (src_file ${ANTLR_GENERATED_SOURCES})

add_custom_target(GenerateParser DEPENDS ${ANTLR_GENERATED_SOURCES})
add_custom_command(OUTPUT ${ANTLR_GENERATED_SOURCES}
		COMMAND
		${CMAKE_COMMAND} -E make_directory ${PROJECT_SOURCE_DIR}/src/generated/
		COMMAND
		${ANTLR4_COMMAND} -Werror -Dlanguage=Cpp -listener -visitor -o ${PROJECT_SOURCE_DIR}/src/generated/ -package generated_parser ${PROJECT_SOURCE_DIR}/Jitterish.g4
		WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
		DEPENDS ${PROJECT_SOURCE_DIR}/Jitterish.g4
)

add_library(jit_rt SHARED
		src/rtlib/jit_runtime.cpp
		src/rtlib/jit_values.h
		src/rtlib/storage.h
		src/rtlib/storage.cpp
		src/rtlib/jit_main.cpp
		src/rtlib/jit_runtime.h
        src/rtlib/json_parser.h
        src/rtlib/json_parser.cpp
)

add_executable(jit
		src/main.cpp
		src/rtlib/jit_values.h
		${ANTLR_GENERATED_SOURCES}
)

target_sources(jit
		PUBLIC
		FILE_SET CXX_MODULES FILES
		src/codegen/CodegenContext.cppm
		src/codegen/Compiler.cppm
)

target_link_libraries(jit_rt PRIVATE nlohmann_json::nlohmann_json)
target_compile_options(jit_rt PRIVATE -Wno-return-type-c-linkage)

add_dependencies(jit GenerateParser)
target_link_libraries(jit antlr4_static jit_rt nlohmann_json::nlohmann_json "-Wl,-rpath,/app/compiler" "-Wl,-rpath,.")
