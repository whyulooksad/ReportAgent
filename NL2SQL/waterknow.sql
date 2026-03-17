create database if not EXISTS waterknow;
/*
 Navicat Premium Data Transfer

 Source Server         : localhost
 Source Server Type    : MySQL
 Source Server Version : 80028
 Source Host           : localhost:3306
 Source Schema         : waterknow
工
 Target Server Type    : MySQL
 Target Server Version : 80028
 File Encoding         : 65001

 Date: 15/10/2025 20:18:11
*/
use waterknow;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for knowledge
-- ----------------------------
DROP TABLE IF EXISTS `knowledge`;
CREATE TABLE `knowledge`  (
  `knowledgeid` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `knowledgecontent` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  `updatetime` datetime NULL DEFAULT NULL,
  `isvector` char(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT 'N',
  `vectortime` datetime NULL DEFAULT NULL,
  `userid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  PRIMARY KEY (`knowledgeid`) USING BTREE,
  INDEX `Refusers1`(`userid` ASC) USING BTREE,
  CONSTRAINT `Refusers1` FOREIGN KEY (`userid`) REFERENCES `users` (`userid`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of knowledge
-- ----------------------------
INSERT INTO `knowledge` VALUES ('1', '流量计算应该为三位有效数字，小于1时保留三位小数，大于等于1小于10保留两位小数，10到100保留一位小数，100到1000取整数，1000以上保留前三四，最后一位位四舍五入到前一位', '2025-10-15 00:00:00', 'N', '2025-10-15 19:36:25', '1');

-- ----------------------------
-- Table structure for templet
-- ----------------------------
DROP TABLE IF EXISTS `templet`;
CREATE TABLE `templet`  (
  `templetid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `templetname` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  `updatetime` datetime NULL DEFAULT NULL,
  `isRead` char(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT 'N',
  `readtime` datetime NULL DEFAULT NULL,
  `userid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`templetid`) USING BTREE,
  INDEX `Refusers2`(`userid` ASC) USING BTREE,
  CONSTRAINT `Refusers2` FOREIGN KEY (`userid`) REFERENCES `users` (`userid`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of templet
-- ----------------------------
INSERT INTO `templet` VALUES ('1', '四川省2025年5月雨水情实况', '5月我省降水量总体偏少，其中甘孜、凉山、攀枝花偏多，其余地区偏少或接近常年。受降雨和电站调蓄影响，全省主要江河来水量除大渡河中游、岷江中游偏多外，其余江河以偏少为主。\r\n一、雨情\r\n2025年5月，我省降水量总体偏少，乐山、雅安、甘孜、凉山、广安降水量超过100mm，其余市州降水量均在100mm以下。其中，巴中、广元、德阳、宜宾、成都、眉山、绵阳、阿坝、达州、泸州、攀枝花降水量在50～100mm之间，自贡、遂宁、资阳、内江、南充降水量小于50mm。\r\n月降雨量较多年同期总体偏少，其中南充、巴中、遂宁、自贡、内江、资阳、广元、达州偏少4～6成，宜宾、泸州、眉山、德阳、阿坝偏少1～3成，广安、雅安、乐山、成都、绵阳总体接近常年，甘孜、凉山、攀枝花偏多3～5成。\r\n二、水情\r\n月内各主要江河来水量与多年同期均值比较：大渡河中游、岷江中游偏多1～4成，雅砻江上中游、安宁河、沱江上游、大渡河上游接近常年，其余各主要江河偏少1～8成。与近10年同期均值比较：大渡河上中游偏多1～3成，雅砻江上中游、安宁河、大渡河下游接近常年，其余各主要江河偏少2～8成。\r\n三、水质\r\n从水质监测情况看，按照《地表水环境质量标准》（GB3838—2002）评价：雅砻江桐子林段、安宁河泸沽段、岷江汶川威州段、岷江都江堰段、大渡河泸定段、大渡河沙湾段、青衣江夹江段、沱江金堂三皇庙段、沱江申家沟段、涪江涪江桥段、嘉陵江南充段、渠江州河达州段水质类别为Ⅱ类，水质较好；岷江彭山段、岷江五通桥段水质类别为Ⅲ类，水质达标。', '2025-10-15 19:42:32', 'N', NULL, '1');

-- ----------------------------
-- Table structure for templetquestion
-- ----------------------------
DROP TABLE IF EXISTS `templetquestion`;
CREATE TABLE `templetquestion`  (
  `questionid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `questioncontent` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `createtime` datetime NULL DEFAULT NULL,
  `isRead` char(1) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT 'N',
  `readtime` datetime NULL DEFAULT NULL,
  `templetid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  PRIMARY KEY (`questionid`) USING BTREE,
  INDEX `Reftemplet3`(`templetid` ASC) USING BTREE,
  CONSTRAINT `Reftemplet3` FOREIGN KEY (`templetid`) REFERENCES `templet` (`templetid`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of templetquestion
-- ----------------------------
INSERT INTO `templetquestion` VALUES ('1', '查询四川省每一个市在某年某月的降雨量', '2025-10-15 20:08:22', 'N', NULL, '1');
INSERT INTO `templetquestion` VALUES ('2', '查询四川省每条江在某年某月的水质情况', '2025-10-15 20:09:37', 'N', NULL, '1');
INSERT INTO `templetquestion` VALUES ('3', '查询四川省每条江在某年某月的水情情况', '2025-10-15 20:13:14', 'N', NULL, '1');

-- ----------------------------
-- Table structure for users
-- ----------------------------
DROP TABLE IF EXISTS `users`;
CREATE TABLE `users`  (
  `userid` char(36) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `username` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `password` varchar(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `feature` varchar(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  PRIMARY KEY (`userid`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of users
-- ----------------------------
INSERT INTO `users` VALUES ('1', 'liming', '123', '查成都市范围的水情');
INSERT INTO `users` VALUES ('2', 'wang', '123', '查乐山市范围的水情');

SET FOREIGN_KEY_CHECKS = 1;
