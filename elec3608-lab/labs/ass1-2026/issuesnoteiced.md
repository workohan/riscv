# my own
* stalling behaviour still unclear when writing to regfile
  * Replace with "smart bubble"? 
* CSR will also cause stalls

# csrfile
* 31'h x -> should be 32 and no space. i left it as 32'hx instead of 32'h0 since it might be useful for debugging and identifing undefined behaviour
* mstatus_bits needs to be assigned
