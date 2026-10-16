if(NOT DEFINED PROGRAM)
  message(FATAL_ERROR "PROGRAM is required")
endif()

execute_process(
  COMMAND "${PROGRAM}"
  RESULT_VARIABLE result
  OUTPUT_VARIABLE output
  ERROR_VARIABLE error
)

if(NOT result EQUAL 64)
  message(FATAL_ERROR
    "expected exit 64, got ${result}; stdout=${output}; stderr=${error}")
endif()
