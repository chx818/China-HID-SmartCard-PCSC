// -*- mode:c++ -*-

#ifndef DCRF32_H_
#define DCRF32_H_

#ifdef WIN32
#include <winsock2.h>
#pragma comment(lib, "ws2_32.lib")
#define API_ATTRIBUTE
#define USER_API __stdcall
#pragma pack(push)
#pragma pack(1)
#else
typedef int HANDLE;
#define API_ATTRIBUTE __attribute__((visibility("default")))
#define USER_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

  /**
   * @brief  打开设备。
   * @par    说明：
   * 建立设备的通讯并且分配相应的资源，大部分功能接口都需要在此过程后才能进行，在不需要使用设备后，必须使用 ::dc_exit 去关闭设备的通讯和释放资源。
   * @param[in] port 端口号。
   * @n 0~99 - 表示串口模式（编号物理对应），编号0表示第一个串口合法设备，编号1表示第二个串口合法设备，以此类推。
   * @n 100~199 - 表示USB模式（编号逻辑对应），编号100表示第一个USB合法设备，编号101表示第二个USB合法设备，以此类推。
   * @param[in] baud 波特率，只针对串口模式有效。
   * @return <0表示失败，否则为设备标识符。
   */
  API_ATTRIBUTE HANDLE USER_API dc_init(short port, int baud);

  /**
   * @brief  关闭设备。
   * @par    说明：
   * 关闭设备的通讯和释放资源。
   * @param[in] icdev 设备标识符。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_exit(HANDLE icdev);

 /**
   * @brief  配置端口名称。
   * @par    说明：
   * 用于配置端口对应的物理名称，在调用 ::dc_init 之前可以使用此接口来改变端口号内部对应的默认物理名称，如Windows平台下0端口号对应的默认名称为"COM1"，Linux平台下0端口号对应的默认名称为"/dev/ttyS0"。
   * @param[in] port 端口号，同 ::dc_init 的 @a port 。
   * @param[in] name 物理名称。
   */
  API_ATTRIBUTE void USER_API dc_config_port_name(short port, const char *name);

  /**
   * @brief  打开设备。
   * @par    说明：
   * 建立设备的通讯并且分配相应的资源，大部分功能接口都需要在此过程后才能进行，在不需要使用设备后，必须使用 ::dc_exit 去关闭设备的通讯和释放资源。
   * @param[in] port 端口号。
   * @n 0~99 - 表示串口模式（编号物理对应），编号0表示第一个串口合法设备，编号1表示第二个串口合法设备，以此类推。
   * @n 100~199 - 表示USB模式（编号逻辑对应），编号100表示第一个USB合法设备，编号101表示第二个USB合法设备，以此类推。
   * @param[in] baud 波特率，只针对串口模式有效。
   * @param[in] name 设备逻辑名称。
   * @return <0表示失败，否则为设备标识符。
   */
  API_ATTRIBUTE HANDLE USER_API dc_init_name(short port, int baud, const char *name);
  
  /**
   * @brief  库入口。
   * @par    说明：
   * 可以获取或设置一些库相关参数，此接口可不掉用，如需调用必须放在所有其它接口之前调用。
   * @param[in] flag 标志，用于决定 @a context 的类型和含义。
   * @n 0 - 表示获取库版本， @a context 类型为char *，请至少分配64个字节。
   * @n 1 - 表示设置库的工作目录， @a context 类型为const char *。
   * @n 2 - 表示设置库调用者的工作目录， @a context 类型为const char *。
   * @param[in,out] context 参数实际类型和含义由 @a flag 的值来决定。
   */
  API_ATTRIBUTE void USER_API LibMain(int flag, void *context);

  /**
   * @brief  数据转换。
   * @par    说明：
   * 普通数据换成十六进制字符串（短转长）。
   * @param[in] hex 要转换的数据。
   * @param[out] a 转换后的字符串。
   * @param[in] length 要转换数据的长度。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API hex_a(unsigned char *hex, unsigned char *a, short length);

  /**
   * @brief  数据转换。
   * @par    说明：
   * 十六进制字符数据转换为普通数据（长转短）。
   * @param[in] a 要转换的数据。
   * @param[out] hex 转换后的数据。
   * @param[in] len 要转换数据的长度。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API a_hex(unsigned char *a, unsigned char *hex, short len); 
 
 /**
   * @brief  获取设备版本。
   * @par    说明：
   * 获取设备内部固件代码的版本。
   * @param[in] icdev 设备标识符。
   * @param[out] sver 返回的版本字符串，请至少分配128个字节。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_getver(HANDLE icdev, unsigned char *sver);

  /**
   * @brief  获取设备定制序列号。
   * @par    说明：
   * 获取设备内部定制的定制序列号，设备默认序列号为空，只有预先定制的设备才会存在可用的序列号。
   * @param[in] icdev 设备标识符。
   * @param[out] snr 返回的定制序列号字符串，请至少分配33个字节。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_readdevsnr(HANDLE icdev, unsigned char *snr);

  /**
   * @brief  获取设备20位唯一识别码。
   * @par    说明：
   * 获取设备内部写入的唯一识别码。
   * @param[in] icdev 设备标识符。
   * @param[out] uid 返回的唯一识别码字符串，请至少分配21个字节。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_GetDeviceUid(HANDLE icdev, char *uid);  
  
  /**
   * @brief  设备蜂鸣。
   * @par    说明：
   * 设备蜂鸣器发出指定时间的蜂鸣声。
   * @param[in] icdev 设备标识符。
   * @param[in] _Msec 蜂鸣时间，单位为10毫秒。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_beep(HANDLE icdev, unsigned short _Msec);
  
 /**
   * @brief  指示灯控制。
   * @par    说明：
   * 控制设备的指示灯。
   * @param[in] icdev 设备标识符。
   * @param[in] cLed 指示灯编号，0表示全部指示灯，1表示第一个指示灯，2表示第二个指示灯，以此类推。
   * @param[in] cOpenFlag 0-点亮，1-熄灭，2-闪烁。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_ctlled(HANDLE icdev, unsigned char cLed, unsigned char cOpenFlag);

  /**
   * @brief  读EEPROM。
   * @par    说明：
   * 读取设备内部EEPROM中的数据。
   * @param[in] icdev 设备标识符。
   * @param[in] offset 偏移地址。
   * @param[in] length 读取长度。
   * @param[out] rec_buffer 返回的数据。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_srd_eeprom(HANDLE icdev, short offset, short length, unsigned char *rec_buffer);

  /**
   * @brief  写EEPROM。
   * @par    说明：
   * 写入数据到设备内部EEPROM中，可以用作数据保存等。
   * @param[in] icdev 设备标识符。
   * @param[in] offset 偏移地址。
   * @param[in] length 写入长度。
   * @param[in] send_buffer 传入数据。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_swr_eeprom(HANDLE icdev, short offset, short length, unsigned char *send_buffer);  

 /**
   * @brief  复位射频。
   * @par    说明：
   * 复位设备的射频，可以关闭，关闭并且启动。
   * @param[in] icdev 设备标识符。
   * @param[in] _Msec 为0表示关闭射频，否则为复位时间，单位为10毫秒，一般调用建议值为10。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_reset(HANDLE icdev, unsigned short _Msec); 

  /**
   * @brief  配置非接触卡类型。
   * @par    说明：
   * 配置需要操作什么类型的非接触式卡，设备上电后默认操作Type A卡，可以使用此接口来改变类型，一般在寻卡前调用此接口。
   * @param[in] icdev 设备标识符。
   * @param[in] cardtype 类型，'A'表示ISO 14443 Type A卡，'B'表示ISO 14443 Type B卡，'1'表示ISO 15693卡，'2'表示ISO 18092卡，'X'表示设备缺省行为（可能支持一个或多个类型）。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_config_card(HANDLE icdev, unsigned char cardtype); 
  
  /**
   * @brief  寻卡请求、防卡冲突、选卡操作。
   * @par    说明：
   * 内部包含了 ::dc_request ::dc_anticoll ::dc_select ::dc_anticoll2 ::dc_select2 ::dc_anticoll3 ::dc_select3 的功能。
   * @param[in] icdev 设备标识符。
   * @param[in] _Mode 模式，同 ::dc_request 的 @a _Mode 。
   * @param[out] SnrLen 返回卡序列号的长度。
   * @param[out] _Snr 返回的卡序列号，请至少分配16个字节。
   * @return <0表示失败，==0表示成功，==1表示无卡或无法寻到卡片。
   */
  API_ATTRIBUTE short USER_API dc_card_n(HANDLE icdev, unsigned char _Mode, unsigned int *SnrLen, unsigned char *_Snr);

  /**
   * @brief  寻卡请求、防卡冲突、选卡操作。
   * @par    说明：
   * ::dc_card_n 的HEX形式接口，参数 @a _Snr 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_card_n_hex(HANDLE icdev, unsigned char _Mode, unsigned int *SnrLen, unsigned char *_Snr);

  /**
   * @brief  非接触式CPU卡复位。
   * @par    说明：
   * 对感应区CPU卡进行复位操作。
   * @param[in] icdev 设备标识符。
   * @param[out] rlen 返回复位信息的长度。
   * @param[out] receive_data 返回的复位信息，请至少分配128个字节。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_pro_resetInt(HANDLE icdev, unsigned char *rlen, unsigned char *receive_data);

  /**
   * @brief  非接触式CPU卡复位。
   * @par    说明：
   * ::dc_pro_resetInt 的HEX形式接口，参数 @a receive_data 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_pro_resetInt_hex(HANDLE icdev, unsigned char *rlen, char *receive_data);

  /**
   * @brief  非接触式CPU卡指令交互。
   * @par    说明：
   * 对感应区CPU卡进行指令交互操作，注意此接口已封装卡协议部分。
   * @param[in] icdev 设备标识符。
   * @param[in] slen 发送数据的长度。
   * @param[in] sendbuffer 发送数据。
   * @param[out] rlen 返回数据的长度。
   * @param[out] databuffer 返回的数据。
   * @param[in] timeout 超时值，此值只在部分设备的底层使用，单位为250毫秒，一般调用建议值为7。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_pro_commandlinkInt(HANDLE icdev, unsigned int slen, unsigned char *sendbuffer, unsigned int *rlen, unsigned char *databuffer, unsigned char timeout);

  /**
   * @brief  非接触式CPU卡指令交互。
   * @par    说明：
   * ::dc_pro_commandlinkInt 的HEX形式接口，参数 @a sendbuffer @a databuffer 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_pro_commandlinkInt_hex(HANDLE icdev, unsigned int slen, char *sendbuffer, unsigned int *rlen, char *databuffer, unsigned char timeout);  

  /**
   * @brief  非接触式CPU卡指令交互。
   * @par    说明：
   * 对感应区CPU卡进行指令交互操作，注意此接口不封装卡协议部分。
   * @param[in] icdev 设备标识符。
   * @param[in] slen 发送数据的长度。
   * @param[in] sendbuffer 发送数据。
   * @param[out] rlen 返回数据的长度。
   * @param[out] databuffer 返回的数据。
   * @param[in] timeout 超时值，此值只在部分设备的底层使用，单位为250毫秒，一般调用建议值为7。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_pro_commandsource_int(HANDLE icdev, unsigned int slen, unsigned char *sendbuffer, unsigned int *rlen, unsigned char *databuffer, unsigned char timeout);

  /**
   * @brief  非接触式CPU卡指令交互。
   * @par    说明：
   * ::dc_pro_commandsource_int 的HEX形式接口，参数 @a sendbuffer @a databuffer 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_pro_commandsource_int_hex(HANDLE icdev, unsigned int slen, char *sendbuffer, unsigned int *rlen, char *databuffer, unsigned char timeout);
  
  /**
   * @brief  寻Type B卡并激活。
   * @par    说明：
   * 对Type B卡进行寻卡和激活。
   * @param[in] icdev 设备标识符。
   * @param[out] rbuf 返回的激活信息，请至少分配128个字节。
   * @return <0表示失败，==0表示成功，==1表示无卡或无法寻到卡片。
   */
  API_ATTRIBUTE short USER_API dc_card_b(HANDLE icdev, unsigned char *rbuf);

  /**
   * @brief  寻Type B卡并激活。
   * @par    说明：
   * ::dc_card_b 的HEX形式接口，参数 @a rbuf 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_card_b_hex(HANDLE icdev, char *rbuf);

  /**
   * @brief  设置当前要操作的SAM卡座。
   * @par    说明：
   * 设置当前要操作的SAM卡座，用于多卡座切换SAM卡操作。
   * @param[in] icdev 设备标识符。
   * @param[in] _Byte 卡座编号。
   * @n 0x0D - SAM1卡座。
   * @n 0x0E - SAM2卡座。
   * @n 0x0F - SAM3卡座。
   * @n 0x11 - SAM4卡座。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_setcpu(HANDLE icdev, unsigned char _Byte);

  /**
   * @brief  接触式CPU卡复位。
   * @par    说明：
   * 对当前卡座CPU卡进行复位操作，此复位为冷复位。
   * @param[in] icdev 设备标识符。
   * @param[out] rlen 返回复位信息的长度。
   * @param[out] databuffer 返回的复位信息，请至少分配128个字节。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_cpureset(HANDLE icdev, unsigned char *rlen, unsigned char *databuffer);

 /**
   * @brief  接触式CPU卡复位。
   * @par    说明：
   * ::dc_cpureset 的HEX形式接口，参数 @a databuffer 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_cpureset_hex(HANDLE icdev, unsigned char *rlen, char *databuffer);

  /**
   * @brief  接触式CPU卡指令交互。
   * @par    说明：
   * 对当前卡座CPU卡进行指令交互操作，注意此接口已封装卡协议部分。
   * @param[in] icdev 设备标识符。
   * @param[in] slen 发送数据的长度。
   * @param[in] sendbuffer 发送数据。
   * @param[out] rlen 返回数据的长度。
   * @param[out] databuffer 返回的数据。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_cpuapduInt(HANDLE icdev, unsigned int slen, unsigned char *sendbuffer, unsigned int *rlen, unsigned char *databuffer);

  /**
   * @brief  接触式CPU卡指令交互。
   * @par    说明：
   * ::dc_cpuapduInt 的HEX形式接口，参数 @a sendbuffer @a databuffer 为HEX格式。
   */
  API_ATTRIBUTE short USER_API dc_cpuapduInt_hex(HANDLE icdev, unsigned int slen, char *sendbuffer, unsigned int *rlen, char *databuffer);

  /**
   * @brief  射频用户属性操作（下电不保留状态）。
   * @par    说明：
   * 射频用户属性操作（下电不保留状态）。
   * @param[in] icdev 设备标识符。
   * @param[in] type 类型。
   * @n 0x00 - 设置用户所有属性为设备缺省值，参数 @a value 无效。
   * @n 0x01 - 设置射频速率，参数 @a value 为入参，==0x00表示106K，==0x11表示212K，==0x33表示424K。
   * @n 0x02 - 获取射频速率，参数 @a value 为出参，==0x00表示106K，==0x11表示212K，==0x33表示424K。
   * @n 0x03 - 设置射频通讯请求WTX次数，参数 @a value 为入参。
   * @n 0x04 - 获取射频通讯请求WTX次数，参数 @a value 为出参。
   * @param[in,out] value 参数含义由 @a type 的值来决定。
   * @return <0表示失败，==0表示成功。
   */
  API_ATTRIBUTE short USER_API dc_RfUserAttributes(HANDLE icdev, unsigned char type, unsigned short *value);  

#ifdef __cplusplus
}
#endif

#ifdef WIN32
#pragma pack(pop)
#endif

#endif // CLREADER_H_
