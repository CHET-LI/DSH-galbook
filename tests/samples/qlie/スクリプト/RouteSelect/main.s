@@@!Layout.s
@@TOP
	\sub,@@!SUBTOP
	\if,ResultStr[0]=="secret"\then
		\go,@@Route_Secret,"シナリオ\Route.s"
	\else
		\go,@@Route_Normal,"シナリオ\Route.s"
	\end
@@!SUBTOP
	\if,#ClearA==0\then
		\scp,eff	\fdi,0,500
		\clk,500
		\cal,ResultStr[0]="Normal"
		\ret
	\end
\ret
